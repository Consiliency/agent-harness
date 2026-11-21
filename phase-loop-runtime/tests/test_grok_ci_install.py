"""The ``grok-catalog`` extra reaches every suite environment in one change set, and the
installed wheel answers without it (GROKROLL §2.2; lane SL-0).

The hosted pytest job installs the runtime by an explicit pip line that does not read the
``test`` dependency group; ``scripts/local_check.py`` (``CI_TEST_DEPS``) and the Gate A suite
container mirror it by hand. All three must name ``[visual,claude-sdk,grok-catalog]``, or the
signature vector test fails for a missing ``cryptography`` (it has no skip path). The
``grok-egress-ns`` job's separate install line is not the suite's and stays as it was.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import tomllib
from pathlib import Path

import pytest
import yaml

RUNTIME = Path(__file__).resolve().parents[1]
REPO = RUNTIME.parent
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"
DAGGER = REPO / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"
SUITE_INSTALL = "./phase-loop-runtime[visual,claude-sdk,grok-catalog]"

pytestmark = pytest.mark.skipif(not WORKFLOW.is_file() or not DAGGER.is_file(),
                                reason="CI plumbing is absent from the standalone layout")


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _runs(job: str) -> list[str]:
    return [step.get("run", "") for step in _jobs()[job]["steps"]]


def _local_check():
    spec = importlib.util.spec_from_file_location("_grok_local_check", RUNTIME / "scripts" / "local_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ec_grokroll_4_the_hosted_install_line_names_the_extra():
    installs = [run for run in _runs("pytest") if "pip install" in run and "./phase-loop-runtime" in run]
    assert len(installs) == 1
    assert f'"{SUITE_INSTALL}"' in installs[0]


def test_ec_grokroll_4_the_local_check_mirror_names_the_extra():
    assert _local_check().CI_TEST_DEPS[0] == SUITE_INSTALL


def test_ec_grokroll_4_the_gate_a_suite_container_names_the_extra():
    lists = []
    for node in ast.walk(ast.parse(DAGGER.read_text())):
        if isinstance(node, ast.List):
            values = [item.value for item in node.elts
                      if isinstance(item, ast.Constant) and isinstance(item.value, str)]
            if "pip" in values and "install" in values and any(
                    value.startswith("./phase-loop-runtime") for value in values):
                lists.append(values)
    assert len(lists) == 1 and SUITE_INSTALL in lists[0]


def test_the_grok_egress_ns_install_line_is_not_the_suites():
    runs = "\n".join(_runs("grok-egress-ns"))
    assert 'python -m pip install pytest "./phase-loop-runtime[visual,claude-sdk]"' in runs
    assert "grok-catalog" not in runs


def test_ec_grokroll_4_the_extra_and_the_test_group_and_the_lock_agree():
    project = tomllib.loads((RUNTIME / "pyproject.toml").read_text())
    extra = project["project"]["optional-dependencies"]["grok-catalog"]
    pins = dict(requirement.split("==") for requirement in extra)
    assert set(pins) == {"cryptography", "brotli"}
    assert "phase-loop-runtime[grok-catalog]" in project["dependency-groups"]["test"]
    lock = (RUNTIME / "uv.lock").read_text()
    for name, version in pins.items():
        assert re.search(rf'\[\[package\]\]\nname = "{name}"\nversion = "{re.escape(version)}"\n',
                         lock), name
    data = project["tool"]["setuptools"]["package-data"]["phase_loop_runtime"]
    assert {"data/grok_releases.json", "data/grok_catalog_gate.json"} <= set(data)


def _wheel_smoke() -> dict:
    steps = [step for step in _jobs()["pytest"]["steps"]
             if "seat-window status --vendor grok" in step.get("run", "")]
    assert len(steps) == 1
    return steps[0]


def test_ec_grokroll_2_the_wheel_smoke_installs_the_wheel_alone_in_its_own_environment():
    step = _wheel_smoke()
    script = step["run"]
    assert step.get("working-directory") == "phase-loop-runtime"
    assert "python -m build --wheel" in script
    venvs = re.findall(r"python -m venv ([^\n]+)", script)
    assert len(venvs) == 1 and "--system-site-packages" not in venvs[0]
    installs = [line.strip() for line in script.splitlines() if "pip install" in line]
    assert len(installs) == 1
    install = installs[0]
    assert install.startswith('"$smoke/venv/bin/python" -m pip install')
    assert install.endswith('"$smoke"/dist/*.whl') and "[" not in install
    assert '"$smoke/venv/bin/python" -I -c "import brotli"' in script
    assert '"$smoke/venv/bin/phase-loop" seat-window status --vendor grok' in script
    assert "rc == 0" in script and "rc == 3" in script and "grok_seat_status.v1" in script


def test_the_wheel_smoke_runs_in_the_ordinary_job_on_every_event():
    job = _jobs()["pytest"]
    assert "pull_request" not in str(job.get("if", ""))
    names = [step.get("name", "") for step in job["steps"]]
    smoke = names.index(_wheel_smoke()["name"])
    install = next(index for index, step in enumerate(job["steps"])
                   if SUITE_INSTALL in step.get("run", ""))
    assert install < smoke
