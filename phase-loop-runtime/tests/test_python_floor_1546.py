"""Python 3.12 is the floor (agent-harness#1546).

Three properties:

* every first-party ``pyproject.toml`` admits no interpreter below 3.12, in
  ``requires-python`` and in its classifiers;
* every CI lane that names an interpreter names 3.12 or newer: the workflows' literal
  ``python-version`` values and the Dagger module's lanes, whose chronology lane must be
  one of the lanes it runs;
* the code the runtime hands to the HOST's ``/usr/bin/python3`` still compiles there.
  That interpreter is not the runtime's: on some hosts it is older than the floor
  (Ubuntu 22.04 ships 3.10), so raising ``requires-python`` does not raise it.

The first two read repository source, which Gate A's standalone-from-wheel tree does not
carry, so they skip there.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest
import yaml
from packaging.specifiers import SpecifierSet

from phase_loop_runtime import panel_invoker, seat_jail, seat_jail_qualification, seat_keyring_exec

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"
FLOOR = (3, 12)
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
def test_the_baml_sweep_runs_one_lane_on_the_floor():
    sweep = yaml.safe_load((WORKFLOWS / "baml-i1-sweep.yml").read_text(encoding="utf-8"))
    assert sweep["jobs"]["sweep"]["strategy"]["matrix"]["python-version"] == ["3.12"]


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
