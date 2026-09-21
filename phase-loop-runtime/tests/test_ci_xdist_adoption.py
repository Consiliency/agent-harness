"""The parallel-suite plumbing must stay identical in both CI consumers.

The hosted GitHub lane and the Dagger offload lane build their own environment
and spell their own pytest invocation. Nothing makes them agree, so a pin bumped
in one and not the other silently gives the two lanes different parallelism --
the class the chronology-node test already guards for the node id
(`test_ci_chronology_scope.py::test_every_consumer_spells_the_same_node_id`).

Adoption measurement and the crash this configuration depends on:
`/mnt/workspace/archives/ci-audit-20260921/xdist/REPORT.md` (Consiliency/agent-harness#945),
and the worker-killing lease guard fixed in Consiliency/agent-harness#950.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"

# The version this repository's xdist-cleanliness was actually measured against.
XDIST_PIN = "pytest-xdist==3.8.0"

# Each flag carries its own reason, so name them individually rather than
# matching one joined string a reformat would break.
REQUIRED_SUITE_FLAGS = ("-n auto", "--dist loadfile", "--max-worker-restart=0")

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


def _commands_only(text: str) -> str:
    """Drop comment lines.

    Both consumers explain these flags in a comment beside them, so a bare
    substring search over the whole file is satisfied by the PROSE and would
    still pass with the flag deleted from the command. Only the executable
    lines may answer "is this flag actually passed?".
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_both_ci_consumers_pin_the_same_pytest_xdist() -> None:
    pattern = re.compile(r'pytest-xdist==\d+\.\d+(?:\.\d+)?')
    workflow_pins = set(pattern.findall(_workflow()))
    dagger_pins = set(pattern.findall(_dagger()))
    assert workflow_pins, "the hosted lane no longer installs pytest-xdist"
    assert dagger_pins, "the Dagger offload lane no longer installs pytest-xdist"
    assert workflow_pins == dagger_pins == {XDIST_PIN}, (
        "the hosted and Dagger lanes disagree on the pytest-xdist pin: "
        f"hosted={sorted(workflow_pins)} dagger={sorted(dagger_pins)}"
    )


@pytest.mark.parametrize("flag", REQUIRED_SUITE_FLAGS)
def test_both_ci_consumers_run_the_suite_with_the_same_parallelism(flag: str) -> None:
    for label, text in (("test.yml", _workflow()), ("ci/dagger main.py", _dagger())):
        assert flag in _commands_only(text), (
            f"{label} no longer passes {flag} to the suite"
        )


def test_both_consumers_spell_the_whole_parallel_configuration_together() -> None:
    """The three flags must sit on one invocation, not be scattered or partial."""
    expected = " ".join(REQUIRED_SUITE_FLAGS)
    for label, text in (("test.yml", _workflow()), ("ci/dagger main.py", _dagger())):
        assert expected in _commands_only(text), (
            f"{label} does not run the suite as `{expected}`"
        )


def test_a_dead_worker_fails_the_lane_instead_of_hanging_it() -> None:
    """`--max-worker-restart=0` is the flag that makes a crash observable.

    Without it xdist replaces the dead worker and this suite's controller stops
    dispatching, so the lane burns its whole timeout with no failing node named.
    Both consumers must carry it, and both must say why.
    """
    for label, text in (("test.yml", _workflow()), ("ci/dagger main.py", _dagger())):
        assert "--max-worker-restart=0" in _commands_only(text), (
            f"{label} dropped the restart cap from the command"
        )
        # The reason must be recorded AGAINST THE FLAG, not merely somewhere in
        # the file: both files already contain unrelated prose, and a check that
        # any of it satisfies would pass with the explanation deleted.
        explained = [
            line for line in text.splitlines()
            if line.lstrip().startswith("#") and "--max-worker-restart=0" in line
        ]
        assert explained, (
            f"{label} carries the restart cap with no comment naming it; a later "
            "reader will take it for tidiness and drop it"
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
