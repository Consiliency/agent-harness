"""The agy verifier's CI wiring after R1 (AGYROLL §3.3; RECBIND SL-1, EC-RECBIND-3/5).

``--contract`` runs on every pull request and push, with no path filter, because the seat
QCI reads files outside any agy-specific path. ``publish-pypi.yml`` gates the build on a
strict conformance run plus ``--release``. The removed gates -- ``--route-core``
(agent-harness#1029) and the full pin ``--source-only`` with ``agy_full_pin_scope.sh``
(agent-harness#1032) -- stay removed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REPO = Path(__file__).resolve().parents[2]
PUBLISH = REPO / ".github" / "workflows" / "publish-pypi.yml"
QUALIFIED = REPO / ".github" / "workflows" / "qualified-agy-image.yml"
REPORT = '"$RUNNER_TEMP/agy-conformance/conformance.xml"'

pytestmark = pytest.mark.skipif(not QUALIFIED.is_file() or not PUBLISH.is_file(),
                                reason="the workflows are repository source")


def _workflow(path):
    value = yaml.safe_load(path.read_text())
    return value, value.get("on", value.get(True))


def test_the_contract_runs_on_every_pull_request_and_push_without_a_path_filter():
    workflow, triggers = _workflow(QUALIFIED)
    assert "pull_request" in triggers and "push" in triggers
    for event in ("pull_request", "push"):
        assert not (triggers[event] or {}).get("paths") and not (triggers[event] or {}).get("paths-ignore")
    assert triggers["push"]["branches"] == ["main"] and "schedule" in triggers
    (step,) = [s for s in workflow["jobs"]["verify"]["steps"] if "verify_qualified_agy_image.py" in s.get("run", "")]
    assert step["run"] == "uv run --locked python scripts/verify_qualified_agy_image.py --contract"
    assert step["working-directory"] == "phase-loop-runtime"
    assert "if" not in step and "continue-on-error" not in step
    assert "if" not in workflow["jobs"]["verify"]


def test_publication_gates_on_strict_conformance_then_release_before_the_build():
    workflow, _ = _workflow(PUBLISH)
    steps = workflow["jobs"]["build"]["steps"]
    names = [step.get("name", "") for step in steps]
    conformance = steps[names.index("Strict agy route conformance (AGYROLL §3.4)")]
    release = steps[names.index("Verify the agy release gate (--release)")]
    assert conformance["env"]["AGY_CONFORMANCE_STRICT"] == "1"
    assert "tests/test_agy_route_conformance.py" in conformance["run"]
    assert f"--junitxml={REPORT}" in conformance["run"]
    assert 'mkdir -p -m 0700 "$RUNNER_TEMP/agy-conformance"' in conformance["run"]
    assert "--release" in release["run"] and f"--conformance-report {REPORT}" in release["run"]
    for step in (conformance, release):
        assert "if" not in step and "continue-on-error" not in step
    assert names.index("Install review sandbox prerequisites") < names.index(conformance["name"]) \
        < names.index(release["name"]) < names.index("Build sdist + wheel")


@pytest.mark.parametrize("path", [PUBLISH, QUALIFIED])
def test_the_removed_gates_stay_removed(path):
    text = path.read_text()
    assert "--source-only" not in text and "--route-core" not in text and "agy_full_pin_scope" not in text


def test_the_full_pin_scope_script_and_old_catalog_are_deleted():
    assert not (SCRIPTS / "agy_full_pin_scope.sh").exists()
    assert not (REPO / "plans" / "evidence" / "qualified-provider-images.json").exists()


def test_the_verifier_has_exactly_the_three_modes():
    text = (SCRIPTS / "verify_qualified_agy_image.py").read_text()
    for flag in ("--contract", "--release", "--upstream-only", "--conformance-report"):
        assert f'"{flag}"' in text
    for flag in ("--source-only", "--route-core"):
        assert f'"{flag}"' not in text
