"""The parallel-suite plumbing must stay identical in both CI consumers.

The hosted GitHub lane and the Dagger offload lane build their own environment
and spell their own pytest invocation. Nothing makes them agree, so a pin bumped
in one and not the other silently gives the two lanes different parallelism --
the class the chronology-node test already guards for the node id
(`test_ci_chronology_scope.py::test_every_consumer_spells_the_same_node_id`).

WHY THIS PINS TEXT INSTEAD OF INTERPRETING IT. Three review rounds of
Consiliency/agent-harness#956 each defeated the previous interpreter of the suite
command: a file-wide substring search (flags moved onto `--collect-only`), a token
subsequence (`-n 0` appended, an `echo` prefix), a bash-like tokenizer (`#` inside
a word, `suite_args+=('-n0')` in single quotes), and even pytest's own parser
(`--maxprocesses=1`, `--pdb`, `-d`, an env prefix, a second `with_env_variable`).
Every interpreter is one unknown spelling behind. So the reviewed configuration is
PINNED: the exact hosted suite block, the exact Dagger `_suite` builder, and the
exact install line. Any edit there -- whatever it spells -- fails here and must
update the pin on purpose, in the same diff a reviewer reads.

Threat model, stated so it is not over-read: this catches plausible edits (careless
or accidental) that change the suite's parallel configuration. It is not a sandbox
against deliberate obfuscation elsewhere in the workflow (redefining `python`
earlier in the step, say); code review covers that.

Adoption measurement and the crash this configuration depends on:
`/mnt/workspace/archives/ci-audit-20260921/xdist/REPORT.md` (Consiliency/agent-harness#945),
and the worker-killing lease guard fixed in Consiliency/agent-harness#950.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"

# The version this repository's xdist-cleanliness was actually measured against.
XDIST_PIN = "pytest-xdist==3.8.0"

# The parallel configuration the pinned blocks carry (named for readable failures).
PARALLEL_FLAGS = "-n auto --dist loadfile --max-worker-restart=0"

# The hosted lane's suite-environment install line, verbatim.
HOSTED_INSTALL_LINE = (
    '        run: python -m pip install "./phase-loop-runtime[visual]" pytest '
    '"pytest-xdist==3.8.0" "build==1.6.1" "setuptools>=70.1"'
)

# sha256 of the reviewed blocks (see `hosted_suite_block` / `dagger_suite_source`).
# Changing either block is allowed; doing it WITHOUT touching this pin is not.
# `_sandbox_exec` is pinned too: it prepends a preflight to the suite script and runs
# both through one `bash -c`, so it is on the suite's execution path.
SANDBOX_EXEC_SHA256 = "8a6bcabbf6db690741c06bf94131b1132d62066300416d434d8d121dca74a353"
HOSTED_SUITE_SHA256 = "89e14f69d867bcf5b49b6f98fb151b8c9017149a9d5f712b024e8061fce765d0"
DAGGER_SUITE_SHA256 = "4f25fe45b21ebd14da522e338953e66fb14ca6ade0c633267f28571bb956fde7"

# The container-env cap for `-n auto` on the offload host: exactly one site, in `_base`.
AUTO_WORKERS_VAR = "PYTEST_XDIST_AUTO_NUM_WORKERS"
AUTO_WORKERS_CAP = "8"

# Ambient pytest configuration that would reach the suite without touching its argv.
AMBIENT_PYTEST_ENV = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD")

# pytest reads the FIRST of these it finds in the rootdir, BEFORE pyproject.toml, so a
# new one would shadow the pyproject check below (and could carry `addopts = -n0`).
SHADOWING_INI_FILES = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg")

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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hosted_suite_block(text: str) -> str | None:
    """From `suite_args=()` through the last continued line of the suite pytest run.

    Comment lines inside the block are INCLUDED: a comment line inserted into a
    backslash continuation ends the command in bash, so it changes behaviour.
    None if the block cannot be delimited unambiguously (fails closed).
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "suite_args=()"]
    if len(starts) != 1:
        return None
    i = starts[0]
    while i < len(lines) and 'python -m pytest -m "not dotfiles_integration"' not in lines[i]:
        i += 1
    if i == len(lines):
        return None
    while i < len(lines) and lines[i].rstrip().endswith("\\"):
        i += 1
    if i == len(lines):
        return None
    return "\n".join(line.rstrip() for line in lines[starts[0]: i + 1])


def dagger_function_source(source: str, name: str) -> str | None:
    """The exact source of one builder method, or None unless there is exactly one."""
    tree = ast.parse(source)
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(found) != 1:
        return None
    return ast.get_source_segment(source, found[0])


def dagger_suite_source(source: str) -> str | None:
    """The exact source of the `_suite` builder (its argv, script and suite_args)."""
    return dagger_function_source(source, "_suite")


def auto_worker_cap_sites(source: str) -> list[tuple[str, str | None]]:
    """Every string constant naming the cap variable: (enclosing function, value set).

    The value is the second argument when the constant is the first argument of a
    `.with_env_variable(...)` call, else None (a mention that is not a setting).
    """
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node: ast.AST) -> str:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    sites: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == AUTO_WORKERS_VAR:
            call = parents.get(node)
            value = None
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "with_env_variable" and call.args and call.args[0] is node
                    and len(call.args) == 2 and isinstance(call.args[1], ast.Constant)):
                value = str(call.args[1].value)
            sites.append((enclosing(node), value))
    return sites


def dagger_install_pins(source: str) -> list[str]:
    """xdist pins in the Dagger `with_exec([... pip install ...])` argv LIST.

    Parsed with `ast`, so only string literals that are elements of the real
    argv list count -- a comment or docstring mentioning the pin does not.
    Every list literal in the module is scanned, not just the suite install: a second
    `with_exec([... "pip", "install", "pytest-xdist==X"])` would upgrade it.
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


def hosted_problems(text: str) -> list[str]:
    problems = []
    block = hosted_suite_block(text)
    if block is None:
        problems.append("the suite block (`suite_args=()` .. suite pytest run) cannot be delimited")
    elif _sha(block) != HOSTED_SUITE_SHA256:
        problems.append(f"the suite block changed (sha256 {_sha(block)}):\n{block}")
    if [line for line in text.splitlines() if line == HOSTED_INSTALL_LINE] == []:
        problems.append(f"the install line is no longer exactly: {HOSTED_INSTALL_LINE.strip()}")
    xdist_lines = [line for line in text.splitlines() if "pytest-xdist" in line]
    if xdist_lines != [HOSTED_INSTALL_LINE]:
        problems.append(f"pytest-xdist must be installed on exactly the pinned line; found {xdist_lines}")
    for name in (*AMBIENT_PYTEST_ENV, AUTO_WORKERS_VAR):
        if name in text:
            problems.append(f"{name} appears in the workflow; it reaches the suite without its argv")
    return problems


def dagger_problems(source: str) -> list[str]:
    problems = []
    suite = dagger_suite_source(source)
    if suite is None:
        problems.append("expected exactly one `_suite` builder")
    elif _sha(suite) != DAGGER_SUITE_SHA256:
        problems.append(f"`_suite` changed (sha256 {_sha(suite)}):\n{suite}")
    sandbox = dagger_function_source(source, "_sandbox_exec")
    if sandbox is None:
        problems.append("expected exactly one `_sandbox_exec`")
    elif _sha(sandbox) != SANDBOX_EXEC_SHA256:
        problems.append(f"`_sandbox_exec` changed (sha256 {_sha(sandbox)}):\n{sandbox}")
    pins = dagger_install_pins(source)
    if pins != [XDIST_PIN]:
        problems.append(f"pytest-xdist must be pinned exactly once, to {XDIST_PIN}; found {pins}")
    sites = auto_worker_cap_sites(source)
    # TEXT count too: an `export {AUTO_WORKERS_VAR}=1` inside a script string is not
    # a constant equal to the name, so the ast site list alone would miss it.
    if source.count(AUTO_WORKERS_VAR) != 1 or sites != [("_base", AUTO_WORKERS_CAP)]:
        problems.append(f"{AUTO_WORKERS_VAR} must be set exactly once, in `_base`, to "
                        f"{AUTO_WORKERS_CAP!r}; found {sites}")
    for name in AMBIENT_PYTEST_ENV:
        if name in source:
            problems.append(f"{name} appears in the Dagger module; it reaches the suite without its argv")
    return problems


_UPDATE_HINT = (
    "\nIf this change is intentional, the suite must still run `" + PARALLEL_FLAGS + "` "
    "in BOTH consumers; then update the pinned sha256 in this file in the same diff."
)


def test_both_ci_consumers_pin_the_same_pytest_xdist() -> None:
    assert HOSTED_INSTALL_LINE in _workflow().splitlines(), "hosted install line changed"
    dagger = dagger_install_pins(_dagger())
    assert dagger == [XDIST_PIN], f"dagger install argv pins {dagger}"


def test_the_hosted_suite_is_the_reviewed_one() -> None:
    problems = hosted_problems(_workflow())
    assert not problems, "\n".join(problems) + _UPDATE_HINT


def test_the_dagger_suite_is_the_reviewed_one() -> None:
    problems = dagger_problems(_dagger())
    assert not problems, "\n".join(problems) + _UPDATE_HINT


@pytest.mark.parametrize("label,block", (
    ("test.yml", lambda: hosted_suite_block(_workflow())),
    ("ci/dagger main.py", lambda: dagger_suite_source(_dagger())),
))
def test_the_pinned_blocks_carry_and_explain_the_parallel_flags(label, block) -> None:
    """Readable companion to the pins: WHAT the reviewed blocks say.

    `--max-worker-restart=0` is the flag that makes a crash observable. Under the
    loadfile/loadscope schedulers, xdist's default of replacing a dead worker leaves
    the controller waiting with every worker idle, so the lane burns its whole
    timeout with no failing node named (`--dist load` recovers instead). The
    explanation lives in a comment inside the pinned block, beside the command.
    """
    text = block()
    assert text is not None
    assert PARALLEL_FLAGS in text, f"{label}: the suite block does not carry {PARALLEL_FLAGS}"
    comments = "\n".join(line for line in text.splitlines() if line.lstrip().startswith("#"))
    assert "--max-worker-restart=0" in comments and "loadfile" in comments, (
        f"{label}: no comment in the suite block explains the restart cap and its loadfile coupling"
    )


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


def test_no_ini_file_shadows_the_pyproject_pytest_config() -> None:
    runtime = REPO_ROOT / "phase-loop-runtime"
    present = [name for name in SHADOWING_INI_FILES if (runtime / name).exists()]
    assert not present, (
        f"{present} would be read INSTEAD of pyproject.toml's [tool.pytest.ini_options]; "
        "it could carry addopts the addopts check never sees"
    )


# --- Every mutation review found against an earlier guard must red this one. ---
# Each is applied to the REAL file text; `old` must occur, so a mutation whose
# anchor drifts fails loudly instead of passing vacuously.

_FLAG_LINE_HOSTED = "            -n auto --dist loadfile --max-worker-restart=0 \\\n"
_SUITE_LINE_HOSTED = '          PYTHONPATH=src:tests python -m pytest -m "not dotfiles_integration" \\\n'
_FLAG_LINE_DAGGER = "  -n auto --dist loadfile --max-worker-restart=0 \\\\\n"

HOSTED_MUTATIONS = (
    ("r1 codex: flags moved onto the collect-only probe",
     _FLAG_LINE_HOSTED, ""),
    ("r2 codex: a later -n 0 wins",
     _FLAG_LINE_HOSTED, _FLAG_LINE_HOSTED + "            -n 0 \\\n"),
    ("r2 codex: echo prefix prints instead of running",
     _SUITE_LINE_HOSTED, _SUITE_LINE_HOSTED.replace("PYTHONPATH=", "echo PYTHONPATH=")),
    ("r2 grok: flags commented out mid-continuation",
     _FLAG_LINE_HOSTED, "            # -n auto --dist loadfile --max-worker-restart=0 \\\n"),
    ("r2 grok: flags handed to a second command",
     "            --ignore tests/test_legible_evidence.py\n",
     "            --ignore tests/test_legible_evidence.py && true -n auto\n"),
    ("r3 self: attached short option -n0",
     _FLAG_LINE_HOSTED, _FLAG_LINE_HOSTED + "            -n0 \\\n"),
    ("r3 codex: single-quoted suite_args addition",
     "          suite_args=()\n", "          suite_args=()\n          suite_args+=('-n0')\n"),
    ("r3 native B1: a second element in an allowed addition",
     '            suite_args+=("--deselect=$CHRONOLOGY_NODE")\n            expect=""\n',
     '            suite_args+=("--deselect=$CHRONOLOGY_NODE" "-n0")\n            expect=""\n'),
    ("r3 native B2: env prefix caps the auto worker count",
     _SUITE_LINE_HOSTED, _SUITE_LINE_HOSTED.replace("PYTHONPATH=", "PYTEST_XDIST_AUTO_NUM_WORKERS=1 PYTHONPATH=")),
    ("r3 native B3: --maxprocesses=1", _FLAG_LINE_HOSTED, _FLAG_LINE_HOSTED + "            --maxprocesses=1 \\\n"),
    ("r3 native B3: --pdb runs serially", _FLAG_LINE_HOSTED, _FLAG_LINE_HOSTED + "            --pdb \\\n"),
    ("r3 native B3: -d switches the scheduler", _FLAG_LINE_HOSTED, _FLAG_LINE_HOSTED + "            -d \\\n"),
    ("r3 native B3: --co runs nothing", _FLAG_LINE_HOSTED, _FLAG_LINE_HOSTED + "            --co \\\n"),
    ("r3 grok: single-quoted restart-cap override",
     "          suite_args=()\n", "          suite_args=()\n          suite_args+=('--max-worker-restart=4')\n"),
    ("r3 grok: two double-quoted words",
     "          suite_args=()\n", '          suite_args=()\n          suite_args+=("-n" "0")\n'),
    ("r3 grok: |& hands the flags to a second command",
     _FLAG_LINE_HOSTED, "            |& true -n auto --dist loadfile --max-worker-restart=0 \\\n"),
    ("step env: PYTEST_ADDOPTS",
     "        working-directory: phase-loop-runtime\n        env:\n"
     "          CHRONOLOGY: ${{ steps.scope.outputs.chronology }}\n",
     "        working-directory: phase-loop-runtime\n        env:\n"
     "          CHRONOLOGY: ${{ steps.scope.outputs.chronology }}\n          PYTEST_ADDOPTS: -n0\n"),
    ("install line: xdist pin dropped", ' "pytest-xdist==3.8.0"', ""),
    ("advisor: a second install upgrades xdist",
     "        run: python -m pip install \"./phase-loop-runtime[visual]\"",
     "        run: python -m pip install \"pytest-xdist==3.9.0\"\n      - name: x\n"
     "        run: python -m pip install \"./phase-loop-runtime[visual]\""),
)

DAGGER_MUTATIONS = (
    ("r2 codex: a later -n 0 wins", _FLAG_LINE_DAGGER, _FLAG_LINE_DAGGER + "  -n 0 \\\\\n"),
    ("r3 codex: '#' inside a word hides -n0 from a tokenizer",
     _FLAG_LINE_DAGGER, _FLAG_LINE_DAGGER + "  --deselect=unused#marker -n0 \\\\\n"),
    ("r3 native B1: suite_args assigned wholesale",
     "        suite_args = []\n", '        suite_args = ["-n0"]\n'),
    ("r3 native B1: suite_args extended",
     "        suite_args = []\n", '        suite_args = []\n        suite_args.extend(["-n0"])\n'),
    ("r3 grok: suite_args += [...]",
     "        suite_args = []\n", '        suite_args = []\n        suite_args += ["-n0"]\n'),
    ("r3 native B4: a second env setting after _base",
     "        return self._sandbox_exec(self._base(source, python_version), script)\n",
     "        return self._sandbox_exec(self._base(source, python_version)"
     '.with_env_variable("PYTEST_XDIST_AUTO_NUM_WORKERS", "1"), script)\n'),
    ("advisor: a second install upgrades xdist",
     '"--no-new-privs", "/bin/bash", "-c", preflight + script],',
     '"--no-new-privs", "/bin/bash", "-c", preflight + script],\n'
     '            ).with_exec(["python", "-m", "pip", "install", "pytest-xdist==3.9.0"],'),
    ("advisor: an export inside the sandbox preflight",
     "set -euo pipefail\npython - <<'PY_CHECK'\n",
     "set -euo pipefail\nexport PYTEST_XDIST_AUTO_NUM_WORKERS=1\npython - <<'PY_CHECK'\n"),
    ("the cap moved out of _base",
     '            .with_env_variable("PYTEST_XDIST_AUTO_NUM_WORKERS", "8")\n', ""),
)


@pytest.mark.parametrize("label,old,new", HOSTED_MUTATIONS, ids=[m[0] for m in HOSTED_MUTATIONS])
def test_every_found_hosted_mutation_is_rejected(label, old, new) -> None:
    text = _workflow()
    assert text.count(old) == 1, f"{label}: mutation anchor no longer occurs exactly once"
    assert not hosted_problems(text), "the unmutated workflow must pass first"
    mutated = text.replace(old, new, 1)
    assert hosted_problems(mutated), f"{label}: accepted"


@pytest.mark.parametrize("label,old,new", DAGGER_MUTATIONS, ids=[m[0] for m in DAGGER_MUTATIONS])
def test_every_found_dagger_mutation_is_rejected(label, old, new) -> None:
    source = _dagger()
    assert source.count(old) == 1, f"{label}: mutation anchor no longer occurs exactly once"
    assert not dagger_problems(source), "the unmutated module must pass first"
    assert dagger_problems(source.replace(old, new, 1)), f"{label}: accepted"


def test_a_pin_surviving_only_in_a_comment_is_rejected() -> None:
    source = _dagger()
    mutated = source.replace(f'"{XDIST_PIN}",', "", 1) + f"\n# {XDIST_PIN}\n"
    assert XDIST_PIN in mutated
    assert dagger_install_pins(mutated) == []
