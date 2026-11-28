"""Contract and live-execution checks for the CI repo-local LEGIBLE assumption-probe step (agent-harness#2024)."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

import test_legible_roadmap_contract as legible_contract


RUNTIME = Path(__file__).resolve().parents[1]
REPO = RUNTIME.parent
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"

REPO_LOCAL_KINDS = frozenset({
    "repo_constant",
    "roadmap_predicate",
    "ast_call_predicate",
    "manifest_behavior",
})
EXCLUDED_KINDS = frozenset({
    "github_pr",
    "github_issue",
    "github_ref",
    "github_comment",
    "remote_json_field",
    "reviewtruth_fable_transition",
    "repo_digest",
})

STEP_NAME = "Run repo-local LEGIBLE assumption-probe live arms"
NODE_PATTERN = re.compile(
    r'"(tests/test_legible_roadmap_contract\.py::'
    r'test_assumption_probe_mutation_and_positive_control\[([^\]]+)\])"'
)

pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file() or not (REPO / ".git").exists(),
    reason="repo-only CI workflow and canonical .git checkout absent from standalone-from-wheel layout",
)


def _pytest_job_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["pytest"]["steps"]


def _live_probe_step() -> dict:
    steps = [s for s in _pytest_job_steps() if s.get("name") == STEP_NAME]
    assert len(steps) == 1, f"expected exactly one {STEP_NAME!r} step, found {len(steps)}"
    return steps[0]


def _step_probe_ids(step: dict) -> list[str]:
    return [probe_id for _node, probe_id in NODE_PATTERN.findall(step["run"])]


def _step_nodes(step: dict) -> list[str]:
    return [node for node, _probe_id in NODE_PATTERN.findall(step["run"])]


def _step_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    wrapper = shim / "python"
    wrapper.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n", encoding="utf-8")
    wrapper.chmod(0o755)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    sub_tmp = tmp_path / "tmp"
    sub_tmp.mkdir(exist_ok=True)

    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("PYTEST_", "GIT_"))
    }
    env.pop("PHASE_LOOP_LAUNCH_AUDIT_PATH", None)
    env.pop("PYTHONOPTIMIZE", None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["TMPDIR"] = str(sub_tmp)
    env["PATH"] = f"{shim}:{env.get('PATH', '')}"
    env["RUNNER_TEMP"] = str(runner_temp)
    # Seed bogus tokens so the test proves the step unsets them and never relies on GitHub auth.
    env["GH_TOKEN"] = "invalid-token-must-be-unset"
    env["GITHUB_TOKEN"] = "invalid-token-must-be-unset"
    return env, runner_temp


def _junit_validator_source(step: dict) -> str:
    match = re.search(r"<<'PY'\n(.*?)\nPY\b", step["run"], re.S)
    assert match is not None, "could not extract JUnit validation script from workflow step"
    return match.group(1)


def test_legible_live_probe_step_placement_and_junit_isolation() -> None:
    steps = _pytest_job_steps()
    names = [s.get("name", "") for s in steps]
    step = _live_probe_step()
    install_idx = next(
        i for i, s in enumerate(steps)
        if "pip install" in str(s.get("run", "")) and "./phase-loop-runtime" in str(s.get("run", ""))
    )
    step_idx = names.index(STEP_NAME)
    assert install_idx < step_idx
    assert step.get("working-directory") == "phase-loop-runtime"

    script = step["run"]
    assert "unset GH_TOKEN GITHUB_TOKEN" in script
    assert "_canonical_repo_ready()" in script
    assert "-p no:cacheprovider" in script
    assert "--junitxml=" in script
    assert "junit-legible-live-probes.xml" in script
    assert "junit-py312.xml" not in script
    assert "continue-on-error" not in step
    assert "|| true" not in script
    assert re.search(r"^\s*assert\b", script, re.M) is None, (
        "fail-closed checkout and JUnit checks must not rely on Python assert (stripped by PYTHONOPTIMIZE=1)"
    )


def test_legible_live_probe_step_selects_exact_repo_local_probe_set() -> None:
    all_probes = legible_contract.ASSUMPTION_PROBES
    known_kinds = {row["kind"] for row in all_probes}
    assert known_kinds == REPO_LOCAL_KINDS | EXCLUDED_KINDS, (
        f"unexpected probe kinds: {known_kinds ^ (REPO_LOCAL_KINDS | EXCLUDED_KINDS)}"
    )

    expected_ids = [row["id"] for row in all_probes if row["kind"] in REPO_LOCAL_KINDS]
    excluded_ids = {row["id"] for row in all_probes if row["kind"] in EXCLUDED_KINDS}

    configured_ids = _step_probe_ids(_live_probe_step())
    assert len(configured_ids) == len(set(configured_ids)), "duplicate probe node IDs in CI step"
    assert set(configured_ids) == set(expected_ids), (
        f"CI repo-local probe set drift: missing={set(expected_ids) - set(configured_ids)}, "
        f"extra={set(configured_ids) - set(expected_ids)}"
    )
    assert not (set(configured_ids) & excluded_ids)


def test_legible_live_probe_step_executes_cleanly_in_canonical_checkout(tmp_path: Path) -> None:
    step = _live_probe_step()
    env, runner_temp = _step_env(tmp_path)
    cache_dir = RUNTIME / ".pytest_cache"
    cache_before = cache_dir.exists()

    proc = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=REPO / step["working-directory"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"CI live-probe step failed (rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    if not cache_before:
        assert not cache_dir.exists(), "live-probe step wrote .pytest_cache into source checkout"

    junit = runner_temp / "junit-legible-live-probes.xml"
    assert junit.is_file()
    root = ET.parse(junit).getroot()
    cases = root.findall(".//testcase")
    expected_names = {
        f"test_assumption_probe_mutation_and_positive_control[{probe_id}]"
        for probe_id in _step_probe_ids(step)
    }
    actual_names = [case.attrib.get("name", "") for case in cases]
    assert len(actual_names) == len(expected_names) and set(actual_names) == expected_names
    for case in cases:
        assert case.find("failure") is None
        assert case.find("error") is None
        assert case.find("skipped") is None


def test_legible_live_probe_step_checks_fail_closed_under_pythonoptimize(tmp_path: Path) -> None:
    step = _live_probe_step()
    env, runner_temp = _step_env(tmp_path)
    env["PYTHONOPTIMIZE"] = "1"

    # 1. Non-canonical copied tree without .git must fail preflight even with PYTHONOPTIMIZE=1.
    copied_repo = tmp_path / "non-canonical"
    copied_runtime = copied_repo / "phase-loop-runtime"
    (copied_repo / "specs").mkdir(parents=True)
    shutil.copytree(RUNTIME / "src", copied_runtime / "src")
    shutil.copytree(RUNTIME / "tests", copied_runtime / "tests")
    shutil.copy2(REPO / "specs" / "phase-plans-v10.md", copied_repo / "specs" / "phase-plans-v10.md")

    preflight = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=copied_runtime,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert preflight.returncode != 0
    assert "expected canonical source checkout" in preflight.stderr
    assert not (runner_temp / "junit-legible-live-probes.xml").exists()

    # 2. JUnit validator must reject both skipped and missing cases even under PYTHONOPTIMIZE=1.
    validator = _junit_validator_source(step)
    nodes = _step_nodes(step)
    expected_names = [node.split("::", 1)[1] for node in nodes]

    skipped_xml = tmp_path / "skipped.xml"
    skipped_cases = "".join(
        f'<testcase name="{name}">{"<skipped/>" if i == 0 else ""}</testcase>'
        for i, name in enumerate(expected_names)
    )
    skipped_xml.write_text(f"<testsuite>{skipped_cases}</testsuite>\n", encoding="utf-8")
    res_skip = subprocess.run(
        [sys.executable, "-O", "-c", validator, str(skipped_xml), *nodes],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res_skip.returncode != 0
    assert "non-passing" in res_skip.stderr

    missing_xml = tmp_path / "missing.xml"
    missing_cases = "".join(f'<testcase name="{name}"/>' for name in expected_names[:-1])
    missing_xml.write_text(f"<testsuite>{missing_cases}</testsuite>\n", encoding="utf-8")
    res_missing = subprocess.run(
        [sys.executable, "-O", "-c", validator, str(missing_xml), *nodes],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res_missing.returncode != 0
    assert "mismatch" in res_missing.stderr
