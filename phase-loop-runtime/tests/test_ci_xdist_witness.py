"""WITNESS that each CI suite lane really runs the reviewed xdist configuration.

`test_ci_xdist_adoption.py` pins the reviewed CI TEXT. Review of agent-harness#956
found edits outside any pinned text that still changed the real run (a conftest
`pytest_xdist_auto_num_workers` hook, a `[tool.pytest] addopts`, a worker cap sourced
from an env file, a second xdist install). So in the CI suite lanes this module
measures the run itself. It lives in its OWN module, deliberately NOT under the
adoption module's "CI files present" skip: a renamed workflow or Dagger module must
not be able to switch the witness off along with the pins (native, pin-round 2).
Outside the CI lanes it skips, and Gate A runs its suite under `env -i`, which clears
the lane gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version as installed_version

import pytest

from tests.test_ci_xdist_adoption import AUTO_WORKERS_CAP, AUTO_WORKERS_VAR, XDIST_PIN


def _expected_min_workers() -> int:
    # Dagger sets the cap in `_base`, so `-n auto` there must be EXACTLY that many
    # (a hook returning 2 would otherwise pass a floor of 2); hosted `-n auto` is the
    # runner's CPU count, which varies, so there the floor is 2.
    return int(AUTO_WORKERS_CAP) if AUTO_WORKERS_VAR in os.environ else 2


def test_nested_run_target() -> None:
    """The one node the witness's nested run executes."""


def _in_ci_suite_lane() -> bool:
    # Hosted: GitHub sets GITHUB_ACTIONS. Dagger: the container env carries the cap.
    return os.environ.get("GITHUB_ACTIONS") == "true" or AUTO_WORKERS_VAR in os.environ


_WITNESS_MARKER = "AGENT_HARNESS_XDIST_WITNESS"

# The nested run's only node: the trivial target below, in THIS module, so the
# witness does not depend on another file's test names (native, pin-round 2).
_WITNESS_NODE = "tests/test_ci_xdist_witness.py::test_nested_run_target"


def test_the_ci_lane_actually_runs_the_pinned_parallelism(request) -> None:
    """WITNESS the real run, not the text: the pins above cannot see a conftest hook,
    a pytest config table, or a second install path, and each of those changed the
    real behaviour in review (native p1: `pytest_xdist_auto_num_workers` -> 1 worker;
    `[tool.pytest] addopts = ["-d"]` -> LoadScheduling; codex p1: a `pip install
    pytest-xdist==3.7.0` through `sh -c` or a requirements file).

    In a CI suite lane this test must itself be running on an xdist worker, and the
    lane's REAL argv -- `workerinput["mainargv"]`, i.e. after bash expansion -- is
    re-run by pytest on one node in the same cwd and environment (so the same
    conftest, pyproject and installed xdist). What xdist's controller settled on --
    recorded by a one-hook plugin, not read from log text -- must be at least two
    workers, the loadfile scheduler and restart cap 0. Nothing in this file parses
    argv. Outside CI it is skipped: developers may run the suite any way they like.
    """
    if not _in_ci_suite_lane():
        pytest.skip("witnesses the CI suite lanes only")
    if os.environ.get(_WITNESS_MARKER):
        pytest.skip("this IS the witness's nested run")
    assert installed_version("pytest-xdist") == XDIST_PIN.split("==")[1], (
        f"installed pytest-xdist is {installed_version('pytest-xdist')}, not the pinned one"
    )
    workerinput = getattr(request.config, "workerinput", None)
    assert workerinput is not None, "the CI suite is not running under xdist workers"
    assert workerinput["workercount"] >= _expected_min_workers(), (
        f"only {workerinput['workercount']} worker(s); expected >= {_expected_min_workers()}"
    )
    assert str(request.config.option.maxworkerrestart) == "0", (
        f"--max-worker-restart is {request.config.option.maxworkerrestart!r}, not 0"
    )
    argv = list(workerinput["mainargv"][1:])
    tmp = request.getfixturevalue("tmp_path")
    # A one-hook plugin for the nested run: xdist calls `pytest_xdist_setupnodes` in
    # the CONTROLLER after it has settled its options (`-d` -> load, `--pdb` -> no, the
    # auto count, `--maxprocesses`), so what it records is the scheduler and worker
    # count xdist actually uses. Structural, not log text: an earlier version grepped
    # xdist's verbose output and a verbosity change false-redded it (codex, pin-round 2).
    (tmp / "ah_xdist_witness.py").write_text(
        "import json, os\n"
        "def pytest_xdist_setupnodes(config, specs):\n"
        "    with open(os.environ['AGENT_HARNESS_XDIST_WITNESS_OUT'], 'w') as fh:\n"
        "        json.dump({'dist': config.getoption('dist'), 'workers': len(specs),\n"
        "                   'maxworkerrestart': config.getoption('maxworkerrestart')}, fh)\n",
        encoding="utf-8",
    )
    record = tmp / "witness.json"
    # The lane's environment, minus this WORKER's own identity (the nested run must be
    # a controller, not believe it is gw0) and the running test's marker.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_XDIST_WORKER") and k not in ("PYTEST_XDIST_TESTRUNUID", "PYTEST_CURRENT_TEST")}
    env[_WITNESS_MARKER] = "1"
    env["AGENT_HARNESS_XDIST_WITNESS_OUT"] = str(record)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(tmp), env.get("PYTHONPATH", "")) if p)
    # The lane's argv carries no positional selection (it is the pinned command), so
    # the appended node is the whole nested run.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *argv, "-p", "ah_xdist_witness",
         f"--junitxml={tmp / 'witness.xml'}", _WITNESS_NODE],
        cwd=request.config.invocation_params.dir, env=env, capture_output=True, text=True, check=False,
        # One trivial node; a hang here is a broken environment, not a slow test.
        timeout=600,
    )
    out = proc.stdout + proc.stderr
    assert record.is_file(), f"xdist never set up worker nodes for the lane's own argv:\n{out[-3000:]}"
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["workers"] >= _expected_min_workers(), f"the lane's own argv runs {seen['workers']} worker(s): {seen}"
    assert seen["dist"] == "loadfile", f"the lane's own argv schedules by {seen['dist']!r}, not loadfile: {seen}"
    assert str(seen["maxworkerrestart"]) == "0", f"the lane's own argv has restart cap {seen['maxworkerrestart']!r}: {seen}"
    assert proc.returncode == 0, f"the witness re-run itself failed (rc={proc.returncode}):\n{out[-3000:]}"
