"""The offload path runs what the hosted path runs, event for event.

`test.yml` runs the suite in one of two places: the hosted lanes (pytest matrix,
wheel smoke, Gate A clean room) or the Dagger module on the offload host. While the
offload was switched off the hosted lanes changed and the module did not: an
offloaded pull request would have run all three interpreters and the full Gate A,
without the quarantine deselect, and without the model-id guard or the doctor that
only the hosted `pytest` job carries. These tests pin the two places together so a
change to one is a red until the other follows.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"
GATE_SCRIPT = REPO_ROOT / "ci" / "offload-gate.sh"

pytestmark = pytest.mark.skipif(
    not WORKFLOW_PATH.is_file() or not DAGGER_MODULE.is_file() or not GATE_SCRIPT.is_file(),
    reason="CI plumbing is absent from the standalone consumer layout",
)

# Hosted `pytest` job steps that are environment setup or are re-expressed by the
# offload job itself, never by the module. Every OTHER step's command must appear in
# the module's suite builder, so a guard added to the hosted lane cannot silently
# stay hosted-only.
HOSTED_SETUP_STEPS = {
    None: "checkout (the offload job checks out the same ref)",
    "Set up Python": "the module's python:<version>-bookworm base image",
    "Install review sandbox prerequisites": "the module's BASE_PACKAGES and _sandbox_exec preflight",
    "Install phase-loop-runtime + pytest": "the module's _base install (pinned by test_ci_xdist_adoption)",
    "Decide whether this run retains the chronology node": "the offload job's own scope step",
    "A non-PR run must retain the chronology node": "the offload job's own retention step",
    "Run standalone test suite": "the suite block itself (pinned by test_ci_xdist_adoption)",
    "Upload chronology junit (py3.10 lane)": "the offload job uploads junit-offload/**",
}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _module_tree() -> ast.Module:
    return ast.parse(DAGGER_MODULE.read_text(encoding="utf-8"))


def _module_constant(name: str):
    for node in _module_tree().body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            if isinstance(node.value, ast.Tuple) and all(
                isinstance(e, ast.Name) for e in node.value.elts
            ):
                return tuple(_module_constant(e.id) for e in node.value.elts)
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a module-level constant in {DAGGER_MODULE}")


def _method_source(name: str) -> str:
    source = DAGGER_MODULE.read_text(encoding="utf-8")
    hits = [
        ast.get_source_segment(source, node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(hits) == 1, f"expected exactly one `{name}` in {DAGGER_MODULE}, found {len(hits)}"
    return hits[0]


def _hosted_pr_versions(job: dict) -> tuple[str, ...]:
    versions = [str(v) for v in job["strategy"]["matrix"]["python-version"]]
    expr = job["strategy"]["matrix"]["exclude"]
    match = re.fullmatch(
        r"\$\{\{ github\.event_name == 'pull_request' && fromJSON\('(.*?)'\) \|\| fromJSON\('\[\]'\) \}\}",
        expr,
    )
    assert match, f"the pytest matrix exclude is no longer the PR-only shape: {expr!r}"
    excluded = {str(e["python-version"]) for e in json.loads(match.group(1))}
    return tuple(v for v in versions if v not in excluded)


def test_pull_request_lane_set_matches_the_hosted_matrix() -> None:
    job = _workflow()["jobs"]["pytest"]
    assert tuple(str(v) for v in job["strategy"]["matrix"]["python-version"]) == _module_constant(
        "PYTHON_VERSIONS"
    )
    assert _hosted_pr_versions(job) == _module_constant("PULL_REQUEST_PYTHON_VERSIONS")


def test_pull_request_runs_the_wheel_smoke_instead_of_gate_a() -> None:
    jobs = _workflow()["jobs"]
    # Hosted: smoke only on a PR, Gate A only off one (agent-harness#1029).
    assert "github.event_name == 'pull_request'" in jobs["wheel-smoke"]["if"]
    assert "github.event_name != 'pull_request'" in jobs["cleanroom"]["if"]
    smoke = next(s for s in jobs["wheel-smoke"]["steps"] if s.get("run") == "bash scripts/gate_a_cleanroom.sh")
    assert smoke["env"] == {"PHASE_LOOP_SKIP_GATE_A_SUITE": "1"}
    module_smoke = _method_source("wheel_smoke")
    assert "export PHASE_LOOP_SKIP_GATE_A_SUITE=1" in module_smoke
    assert "bash scripts/gate_a_cleanroom.sh" in module_smoke
    stages = _method_source("all")
    assert re.search(
        r'\("wheel-smoke", None, self\.wheel_smoke\(source\)\)\s*if pull_request\s*'
        r'else \("gate-a", "gate-a", self\.gate_a\(source, chronology\)\)',
        stages,
    ), "`all` must run the wheel smoke on a pull request and Gate A otherwise"
    assert "PULL_REQUEST_PYTHON_VERSIONS if pull_request else PYTHON_VERSIONS" in stages


def test_quarantine_deselect_follows_the_event_in_both_places() -> None:
    suite_step = next(
        s for s in _workflow()["jobs"]["pytest"]["steps"] if s.get("name") == "Run standalone test suite"
    )
    assert suite_step["env"]["PHASE_LOOP_DESELECT_QUARANTINE"] == (
        "${{ github.event_name == 'pull_request' && '1' || '0' }}"
    )
    suite = _method_source("_suite")
    assert 'quarantine = "1" if pull_request else "0"' in suite
    assert "export PHASE_LOOP_DESELECT_QUARANTINE={quarantine}" in suite


def test_every_hosted_check_runs_on_the_offload_path_too() -> None:
    suite = _method_source("_suite")
    unaccounted = []
    for step in _workflow()["jobs"]["pytest"]["steps"]:
        name = step.get("name")
        if name in HOSTED_SETUP_STEPS:
            continue
        command = (step.get("run") or "").strip()
        if not command or command not in suite:
            unaccounted.append(name)
    assert unaccounted == [], (
        f"hosted pytest steps with no counterpart in the module's `_suite`: {unaccounted}. "
        "Run the same command in `_suite`, or, if it is setup the offload job already "
        "provides, list it in HOSTED_SETUP_STEPS with the reason."
    )


def test_offload_job_hands_the_event_to_the_gate_script() -> None:
    offload = _workflow()["jobs"]["offload"]
    step = next(s for s in offload["steps"] if "dagger-offload@" in s.get("uses", ""))
    assert step["env"]["OFFLOAD_PULL_REQUEST"] == "${{ github.event_name == 'pull_request' }}"


_DAGGER_ARGS_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" >"$STUB_ARGS"
for a in "$@"; do case "$a" in --path=*) mkdir -p "${a#--path=}"; echo stub >"${a#--path=}/verdicts.txt";; esac; done
"""


@pytest.mark.parametrize("value,expected", [(None, "false"), ("false", "false"), ("true", "true")])
def test_gate_script_passes_the_stage_set_to_dagger(tmp_path: Path, value, expected) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "dagger"
    stub.write_text(_DAGGER_ARGS_STUB)
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("AGENT_DAGGER", "DOCKER_HOST", "OFFLOAD_PULL_REQUEST")}
    env.update({"PATH": f"{bindir}:{env['PATH']}", "STUB_ARGS": str(tmp_path / "args"), "CHRONOLOGY": "false"})
    if value is not None:
        env["OFFLOAD_PULL_REQUEST"] = value
    r = subprocess.run(["bash", str(GATE_SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    args = (tmp_path / "args").read_text().splitlines()
    assert f"--pull-request={expected}" in args, args


def test_gate_script_refuses_an_unknown_stage_set(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("AGENT_DAGGER", "DOCKER_HOST")}
    env.update({"OFFLOAD_PULL_REQUEST": "yes", "CHRONOLOGY": "false"})
    r = subprocess.run(["bash", str(GATE_SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "OFFLOAD_PULL_REQUEST must be 'true' or 'false'" in r.stderr
