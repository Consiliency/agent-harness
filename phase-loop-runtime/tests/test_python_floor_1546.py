"""Python 3.12 is the floor (agent-harness#1546); CI runs on Python 3.14.10.

Five properties:

* every first-party ``pyproject.toml`` admits no interpreter below 3.12, in
  ``requires-python`` and in its classifiers;
* every CI lane that names an interpreter names 3.12 or newer: the workflows' literal
  ``python-version`` values and the Dagger module's lanes, whose chronology lane must be
  one of the lanes it runs;
* every interpreter the repository pins for CI and tooling (workflow ``python-version``
  literals, the Dagger lanes and Gate A, ``local_check.py``'s venv) is an exact CPython
  3.14 patch no older than 3.14.10, the first uv-managed 3.14 build with
  ``os.memfd_create``. The deliberately different python3.12 that Dagger grafts in for
  the interpreter-pin tests is the one exemption;
* the interpreter running this suite exposes ``os.memfd_create`` with sealing on Linux
  CPython, so a build without it cannot carry a green lane;
* the code the runtime hands to the HOST's ``/usr/bin/python3`` still compiles there.
  That interpreter is not the runtime's: on some hosts it is older than the floor
  (Ubuntu 22.04 ships 3.10), so raising ``requires-python`` does not raise it.

The repository-source checks skip in Gate A's standalone-from-wheel tree, which does not
carry that source. The memfd check reads none, so it runs there too.
"""

from __future__ import annotations

import ast
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from packaging.specifiers import SpecifierSet

from phase_loop_runtime import panel_invoker, seat_jail, seat_jail_qualification, seat_keyring_exec

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"
LOCAL_CHECK = REPO_ROOT / "phase-loop-runtime" / "scripts" / "local_check.py"
FLOOR = (3, 12)
# The CI and tooling interpreter: an exact 3.14 patch, at least 3.14.10. uv's 3.14.5
# build lacks os.memfd_create, which the immutable-snapshot path needs.
CI_INTERPRETER_MINOR = (3, 14)
CI_INTERPRETER_MIN_PATCH = 10
BELOW_FLOOR = ("3.8", "3.9", "3.10", "3.11")
SYSTEM_PYTHON = Path("/usr/bin/python3")

source_checkout = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists() or not WORKFLOWS.is_dir(),
    reason="repository source absent from the standalone-from-wheel layout",
)


def _first_party_pyprojects() -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", "*pyproject.toml"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    # Test fixtures model other repositories; they are not packages of this one.
    return [REPO_ROOT / p for p in listed if "/fixtures/" not in f"/{p}"]


@source_checkout
def test_every_first_party_pyproject_admits_nothing_below_the_floor():
    import tomllib

    pyprojects = _first_party_pyprojects()
    names = {p.parent.name for p in pyprojects}
    assert {"phase-loop-runtime", "consiliency-harness"} <= names, names
    offenders = []
    for path in pyprojects:
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        requires = project.get("requires-python")
        if requires is None:
            offenders.append(f"{path}: no requires-python")
            continue
        spec = SpecifierSet(requires)
        admitted = [v for v in BELOW_FLOOR if spec.contains(f"{v}.99")]
        if admitted or not spec.contains("3.14.0"):
            offenders.append(f"{path}: requires-python {requires!r} admits {admitted}")
        for classifier in project.get("classifiers", []):
            if any(classifier == f"Programming Language :: Python :: {v}" for v in BELOW_FLOOR):
                offenders.append(f"{path}: classifier {classifier!r}")
    assert not offenders, offenders


def _python_versions(node) -> list[str]:
    """Every literal value of a ``python-version`` key anywhere in a workflow document."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "python-version":
                found += [str(v) for v in (value if isinstance(value, list) else [value])]
            else:
                found += _python_versions(value)
    elif isinstance(node, list):
        for item in node:
            found += _python_versions(item)
    return found


def _at_least_floor(version: str) -> bool:
    major, minor = (int(part) for part in version.split(".")[:2])
    return (major, minor) >= FLOOR


@source_checkout
def test_every_workflow_interpreter_is_at_least_the_floor():
    seen, below = 0, []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for version in _python_versions(yaml.safe_load(workflow.read_text(encoding="utf-8"))):
            if version.startswith("${{"):
                continue  # an expression: its literal is checked where it is defined (a matrix)
            seen += 1
            if not _at_least_floor(version):
                below.append(f"{workflow.name}: {version}")
    assert seen, "no literal python-version found: the walk no longer reads the workflows"
    assert not below, below


@source_checkout
def test_the_baml_sweep_runs_one_lane_on_the_ci_interpreter():
    sweep = yaml.safe_load((WORKFLOWS / "baml-i1-sweep.yml").read_text(encoding="utf-8"))
    assert sweep["jobs"]["sweep"]["strategy"]["matrix"]["python-version"] == ["3.14.10"]


@pytest.mark.skipif(not DAGGER_MODULE.is_file(), reason="Dagger module absent outside a source checkout")
def test_the_dagger_lanes_are_at_least_the_floor_and_keep_the_chronology_lane():
    values = {}
    for node in ast.parse(DAGGER_MODULE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PYTHON_VERSIONS", "CHRONOLOGY_PYTHON"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    assert set(values) == {"PYTHON_VERSIONS", "CHRONOLOGY_PYTHON"}, values
    assert values["PYTHON_VERSIONS"] and all(_at_least_floor(v) for v in values["PYTHON_VERSIONS"])
    assert values["CHRONOLOGY_PYTHON"] in values["PYTHON_VERSIONS"]


def _pinned_ci_interpreter_problem(version: str) -> str | None:
    """Why ``version`` is not an acceptable CI pin, or ``None`` when it is.

    A pin must be three integers: a two-part ``'3.14'`` cannot prove the patch, and
    setup-python or uv would then pick whichever 3.14 they have. It must be 3.14 itself
    (a tuple comparison alone would admit 3.15, contrary to the cp314 target) at patch
    10 or later.
    """
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "not an exact three-part version"
    major, minor, patch = (int(part) for part in parts)
    if (major, minor) != CI_INTERPRETER_MINOR:
        return f"not CPython {CI_INTERPRETER_MINOR[0]}.{CI_INTERPRETER_MINOR[1]}"
    if patch < CI_INTERPRETER_MIN_PATCH:
        return f"patch {patch} is older than {CI_INTERPRETER_MIN_PATCH}"
    return None


def _module_constants(path: Path, names: set[str]) -> dict[str, object]:
    found = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in names:
                found[node.targets[0].id] = ast.literal_eval(node.value)
    return found


@pytest.mark.parametrize("version,ok", [
    ("3.14.10", True), ("3.14.11", True),
    ("3.14", False), ("3.14.5", False), ("3.12", False), ("3.15.0", False), ("3.14.x", False),
])
def test_the_ci_interpreter_rule_itself(version, ok):
    assert (_pinned_ci_interpreter_problem(version) is None) is ok


@source_checkout
@pytest.mark.skipif(not DAGGER_MODULE.is_file() or not LOCAL_CHECK.is_file(),
                    reason="Dagger module or local_check.py absent outside a source checkout")
def test_every_pinned_ci_interpreter_is_at_least_3_14_10():
    offenders, seen = [], 0

    def check(where: str, version: object) -> None:
        nonlocal seen
        seen += 1
        problem = _pinned_ci_interpreter_problem(str(version))
        if problem:
            offenders.append(f"{where}: {version!r} ({problem})")

    # (a) Every literal workflow python-version; an expression is checked where it is
    # defined (a matrix literal, which this same walk reads).
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for version in _python_versions(yaml.safe_load(workflow.read_text(encoding="utf-8"))):
            if not version.startswith("${{"):
                check(workflow.name, version)

    # (b) The Dagger suite lanes and the chronology lane.
    dagger = _module_constants(DAGGER_MODULE, {"PYTHON_VERSIONS", "CHRONOLOGY_PYTHON"})
    assert set(dagger) == {"PYTHON_VERSIONS", "CHRONOLOGY_PYTHON"}, dagger
    for version in dagger["PYTHON_VERSIONS"]:
        check("dagger PYTHON_VERSIONS", version)
    check("dagger CHRONOLOGY_PYTHON", dagger["CHRONOLOGY_PYTHON"])

    # (c) Every container base the module builds takes its interpreter from a checked
    # constant: Gate A and the closure stage name CHRONOLOGY_PYTHON, and the suite lanes
    # pass through the `python_version` they were given from PYTHON_VERSIONS. A string
    # literal here would bypass (b).
    tree = ast.parse(DAGGER_MODULE.read_text(encoding="utf-8"))
    base_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_base"
    ]
    assert base_calls, "no self._base(...) call found: the walk no longer reads the Dagger module"
    for call in base_calls:
        argument = call.args[1] if len(call.args) > 1 else next(
            (kw.value for kw in call.keywords if kw.arg == "python_version"), None)
        if not (isinstance(argument, ast.Name) and argument.id in {"CHRONOLOGY_PYTHON", "python_version"}):
            offenders.append(f"dagger _base call at line {call.lineno}: {ast.unparse(argument) if argument else None}")
    # Every image the module pulls is either the lane's own `python:<lane>-bookworm` or
    # the explicitly exempt test-only graft: a deliberately different python3.12 the
    # `automation.python: python3.12` pin tests resolve (never the suite interpreter).
    images = sorted({
        ast.unparse(node.args[0]) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "from_"
    })
    assert images == ["PIN_INTERPRETER_IMAGE", "f'python:{python_version}-bookworm'"], images

    # (d) make check / local_check.py's venv interpreter.
    local = _module_constants(LOCAL_CHECK, {"VENV_PYTHON"})
    assert "VENV_PYTHON" in local, "local_check.py no longer defines VENV_PYTHON"
    check("local_check.py VENV_PYTHON", local["VENV_PYTHON"])

    assert seen > 3, "too few pins found: the walk no longer reads the workflows"
    assert not offenders, offenders


@pytest.mark.skipif(sys.platform != "linux" or platform.python_implementation() != "CPython",
                    reason="memfd sealing is a Linux CPython capability")
def test_linux_cpython_exposes_memfd_sealing():
    # A build-feature check, not proof that the kernel seals: the runtime's own sealing
    # path still fails closed. It reads no repository source, so it runs in every suite
    # lane and in Gate A's wheel tree, and a uv 3.14.5-style build fails it.
    assert hasattr(os, "memfd_create"), f"{sys.version} lacks os.memfd_create"
    assert hasattr(os, "MFD_ALLOW_SEALING"), f"{sys.version} lacks os.MFD_ALLOW_SEALING"


# The programs the runtime runs under the host's /usr/bin/python3 rather than its own
# interpreter: the seat-side descriptor closers, the journal collector, the jail
# qualification's probe and the keyring step's bound file.
HOST_INTERPRETER_SOURCES = {
    "seat_jail._FD_CLOSER": lambda: seat_jail._FD_CLOSER,
    "panel_invoker._SEAT_FD_CLOSER": lambda: panel_invoker._SEAT_FD_CLOSER,
    "panel_invoker._CLAUDE_JOURNAL_COLLECTOR": lambda: panel_invoker._CLAUDE_JOURNAL_COLLECTOR,
    "seat_jail_qualification._PROBE_SOURCE": lambda: seat_jail_qualification._PROBE_SOURCE,
    "seat_keyring_exec.py": lambda: Path(seat_keyring_exec.__file__).read_text(encoding="utf-8"),
}
OLDEST_HOST_INTERPRETER = (3, 10)


@pytest.mark.parametrize("name", sorted(HOST_INTERPRETER_SOURCES))
def test_host_interpreter_programs_keep_the_oldest_host_grammar(name):
    ast.parse(HOST_INTERPRETER_SOURCES[name](), filename=name, feature_version=OLDEST_HOST_INTERPRETER)


@pytest.mark.skipif(not SYSTEM_PYTHON.is_file(), reason="no /usr/bin/python3 on this host")
@pytest.mark.parametrize("name", sorted(HOST_INTERPRETER_SOURCES))
def test_host_interpreter_programs_compile_under_this_hosts_system_python(name):
    result = subprocess.run(
        [str(SYSTEM_PYTHON), "-I", "-S", "-c",
         "import sys; compile(sys.stdin.read(), sys.argv[1], 'exec')", name],
        input=HOST_INTERPRETER_SOURCES[name](), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
