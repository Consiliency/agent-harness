"""Contract and live-execution checks for the CI canonical manifest step (agent-harness#1730)."""

from __future__ import annotations

import json
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


RUNTIME = Path(__file__).resolve().parents[1]
REPO = RUNTIME.parent
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"

STEP_NAME = "Validate canonical repository manifest"
EXPECTED_NODE = (
    "tests/test_legible_roadmap_contract.py"
    "::test_repository_manifest_exactly_covers_execution_scope"
)
NODE_PATTERN = re.compile(r'"(tests/test_legible_roadmap_contract\.py::[^"]+)"')
# Measured ~24s per canonical step run on an idle 24-core host; allow ample
# headroom under loaded multi-worker hosted CI so CPU contention never trips a
# false timeout (follow-up to agent-harness#1730 / agent-harness#2269).
_STEP_TIMEOUT_S = 180
_CLONE_TIMEOUT_S = 120
_PREFLIGHT_TIMEOUT_S = 90
_VALIDATOR_TIMEOUT_S = 60

pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file() or not (REPO / ".git").exists(),
    reason="repo-only CI workflow and canonical .git checkout absent from standalone-from-wheel layout",
)


def _pytest_job_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["pytest"]["steps"]


def _manifest_step() -> dict:
    steps = [s for s in _pytest_job_steps() if s.get("name") == STEP_NAME]
    assert len(steps) == 1, f"expected exactly one {STEP_NAME!r} step, found {len(steps)}"
    return steps[0]


def _step_nodes(step: dict) -> list[str]:
    return NODE_PATTERN.findall(step["run"])


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
    env["GH_TOKEN"] = "invalid-token-must-be-unset"
    env["GITHUB_TOKEN"] = "invalid-token-must-be-unset"
    return env, runner_temp


def _junit_validator_source(step: dict) -> str:
    match = re.search(r"<<'PY'\n(.*?)\nPY\b", step["run"], re.S)
    assert match is not None, "could not extract JUnit validation script from workflow step"
    return match.group(1)


def test_canonical_manifest_step_placement_and_junit_isolation() -> None:
    steps = _pytest_job_steps()
    names = [s.get("name", "") for s in steps]
    step = _manifest_step()
    install_idx = next(
        i for i, s in enumerate(steps)
        if "pip install" in str(s.get("run", "")) and "./phase-loop-runtime" in str(s.get("run", ""))
    )
    step_idx = names.index(STEP_NAME)
    assert install_idx < step_idx
    assert step.get("working-directory") == "phase-loop-runtime"

    # Preserve standalone-from-wheel clean-room coverage alongside the canonical step.
    assert any(
        '"$suite_root/tests/test_legible_roadmap_contract.py"' in str(s.get("run", ""))
        for s in steps
    ), "standalone-from-wheel test_legible_roadmap_contract.py step must remain intact"

    script = step["run"]
    assert "unset GH_TOKEN GITHUB_TOKEN" in script
    assert "_canonical_repo_ready()" in script
    assert "-p no:cacheprovider" in script
    assert "--junitxml=" in script
    assert "junit-canonical-manifest.xml" in script
    assert "junit-py312.xml" not in script
    assert "continue-on-error" not in step
    assert "|| true" not in script
    assert _step_nodes(step) == [EXPECTED_NODE]
    assert re.search(r"^\s*assert\b", script, re.M) is None, (
        "fail-closed checkout and JUnit checks must not rely on Python assert (stripped by PYTHONOPTIMIZE=1)"
    )


def test_canonical_manifest_step_passes_in_canonical_checkout(tmp_path: Path) -> None:
    step = _manifest_step()
    env, runner_temp = _step_env(tmp_path)
    cache_dir = RUNTIME / ".pytest_cache"
    cache_before = cache_dir.exists()

    proc = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=REPO / step["working-directory"],
        env=env,
        capture_output=True,
        text=True,
        timeout=_STEP_TIMEOUT_S,
    )
    assert proc.returncode == 0, (
        f"CI canonical manifest step failed (rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    if not cache_before:
        assert not cache_dir.exists(), "manifest step wrote .pytest_cache into source checkout"

    junit = runner_temp / "junit-canonical-manifest.xml"
    assert junit.is_file()
    root = ET.parse(junit).getroot()
    cases = root.findall(".//testcase")
    expected_name = EXPECTED_NODE.split("::", 1)[1]
    assert [c.attrib.get("name", "") for c in cases] == [expected_name]
    assert cases[0].find("failure") is None
    assert cases[0].find("error") is None
    assert cases[0].find("skipped") is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_summary", "stale detailed summary on a phase row"),
        ("acceptance_criteria_count", 3),
    ],
)
def test_canonical_manifest_step_fails_on_non_null_detailed_only_field_in_phase_row(
    tmp_path: Path, field: str, value: object,
) -> None:
    """Negative and positive control for agent-harness#1730 and agent-harness#1728: a non-null
    detailed-only value on a phase row fails the exact CI step, and repairing it
    back to null passes."""
    step = _manifest_step()
    env, runner_temp = _step_env(tmp_path)
    copied_repo = tmp_path / "canonical-copy"

    subprocess.run(
        ["git", "clone", "--shared", "-q", str(REPO), str(copied_repo)],
        env=env,
        check=True,
        timeout=_CLONE_TIMEOUT_S,
    )
    manifest_path = copied_repo / "plans" / "manifest.json"
    original_bytes = manifest_path.read_bytes()
    data = json.loads(original_bytes.decode("utf-8"))
    phase_entry = next(entry for entry in data["plans"] if entry.get("type") == "phase")
    phase_entry[field] = value
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # Negative control: mutated phase row must fail the hosted step.
    failed = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=copied_repo / step["working-directory"],
        env=env,
        capture_output=True,
        text=True,
        timeout=_STEP_TIMEOUT_S,
    )
    assert failed.returncode != 0, (
        f"expected CI step to fail on non-null phase.{field}\n"
        f"stdout:\n{failed.stdout}\nstderr:\n{failed.stderr}"
    )
    combined = failed.stdout + "\n" + failed.stderr
    assert "mixes detailed-only fields into a phase entry" in combined, combined

    # Positive control: restoring the corrected manifest passes the exact same step.
    manifest_path.write_bytes(original_bytes)
    junit = runner_temp / "junit-canonical-manifest.xml"
    if junit.exists():
        junit.unlink()
    passed = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=copied_repo / step["working-directory"],
        env=env,
        capture_output=True,
        text=True,
        timeout=_STEP_TIMEOUT_S,
    )
    assert passed.returncode == 0, (
        f"expected repaired manifest to pass CI step (rc={passed.returncode})\n"
        f"stdout:\n{passed.stdout}\nstderr:\n{passed.stderr}"
    )
    assert junit.is_file()


def test_canonical_manifest_step_fails_closed_under_pythonoptimize(tmp_path: Path) -> None:
    step = _manifest_step()
    env, runner_temp = _step_env(tmp_path)
    env["PYTHONOPTIMIZE"] = "1"

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
        timeout=_PREFLIGHT_TIMEOUT_S,
    )
    assert preflight.returncode != 0
    assert "expected canonical source checkout" in preflight.stderr
    assert not (runner_temp / "junit-canonical-manifest.xml").exists()

    validator = _junit_validator_source(step)
    nodes = _step_nodes(step)
    expected_name = nodes[0].split("::", 1)[1]

    skipped_xml = tmp_path / "skipped.xml"
    skipped_xml.write_text(
        f'<testsuite><testcase name="{expected_name}"><skipped/></testcase></testsuite>\n',
        encoding="utf-8",
    )
    res_skip = subprocess.run(
        [sys.executable, "-O", "-c", validator, str(skipped_xml), *nodes],
        env=env,
        capture_output=True,
        text=True,
        timeout=_VALIDATOR_TIMEOUT_S,
    )
    assert res_skip.returncode != 0
    assert "non-passing" in res_skip.stderr

    empty_xml = tmp_path / "empty.xml"
    empty_xml.write_text("<testsuite></testsuite>\n", encoding="utf-8")
    res_empty = subprocess.run(
        [sys.executable, "-O", "-c", validator, str(empty_xml), *nodes],
        env=env,
        capture_output=True,
        text=True,
        timeout=_VALIDATOR_TIMEOUT_S,
    )
    assert res_empty.returncode != 0
    assert "mismatch" in res_empty.stderr
