"""Static contract for the CI chronology-node scope (``ci/chronology-scope.sh``).

The heavy CONFORM chronology node (~50 min, ~88 % of a per-PR CI run's wall
clock) is retained on every push to main, on the nightly schedule, and on any
pull request whose diff touches one of the node's inputs; every other pull
request deselects it. This module pins the three properties that make that
scoping safe:

* every input the node reads -- the mutation definitions' source paths and the
  files that hold their target node ids -- is classified as a chronology input
  by the scope script, so a PR editing one of them can never skip the node;
* the node id is a single literal, and every consumer (the scope script, the
  Dagger module, the hosted workflow, Gate A) spells it identically;
* the script fails CLOSED: any event it cannot classify, and any pull request
  it cannot diff, retains the node.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from _outside_agent_canonical import CONFORM_MUTATION_DEFINITIONS


REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPE_SCRIPT = REPO_ROOT / "ci" / "chronology-scope.sh"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
PUBLISH_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "publish-pypi.yml"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"
GATE_A_SCRIPT = REPO_ROOT / "phase-loop-runtime" / "scripts" / "gate_a_cleanroom.sh"

CHRONOLOGY_NODE = (
    "tests/test_outside_agent_conform_evidence.py::"
    "test_mutation_definitions_are_frozen_but_not_executed_preimplementation"
)

# The scope script and the workflows are repository source, not wheel/package
# data, so Gate A's copied standalone tree cannot evaluate these assertions.
pytestmark = pytest.mark.skipif(
    not SCOPE_SCRIPT.is_file() or not WORKFLOW_PATH.is_file(),
    reason="repo-only CI scope script absent from standalone-from-wheel layout",
)


def _scope(*args: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> str:
    base = {k: v for k, v in os.environ.items() if not k.startswith(("CHRONOLOGY", "GITHUB_"))}
    if env:
        base.update(env)
    result = subprocess.run(
        ["bash", str(SCOPE_SCRIPT), *args],
        check=True,
        capture_output=True,
        text=True,
        env=base,
        cwd=str(cwd or REPO_ROOT),
    )
    return result.stdout.strip()


def _chronology_inputs() -> set[str]:
    """Every repo-relative path the chronology node reads, from the frozen corpus."""
    inputs: set[str] = set()
    for mutation in CONFORM_MUTATION_DEFINITIONS.values():
        inputs.add(mutation.source_path)
        for nodeid in (
            mutation.expected_nodeid,
            mutation.companion_expected_nodeid,
            *mutation.argv,
            *mutation.positive_control,
            *(mutation.companion_argv or ()),
        ):
            if nodeid and "::" in nodeid:
                inputs.add(nodeid.split("::", 1)[0])
    # The node's own body and the shared corpus module it imports.
    inputs.add("phase-loop-runtime/" + CHRONOLOGY_NODE.split("::", 1)[0])
    inputs.add("phase-loop-runtime/tests/_outside_agent_canonical.py")
    return inputs


def test_every_chronology_input_is_classified_as_an_input() -> None:
    inputs = _chronology_inputs()
    assert inputs, "the frozen corpus names no inputs -- the fixture is broken"
    misses = sorted(path for path in inputs if _scope("--match", path) != "match")
    assert not misses, f"chronology inputs the scope script would let a PR skip: {misses}"
    # A negative control: prose cannot change what the node computes.
    assert _scope("--match", "README.md") == "no-match"
    assert _scope("--match", "docs/agent-phase-convergence.md") == "no-match"


def test_every_consumer_spells_the_same_node_id() -> None:
    assert _scope("--node") == CHRONOLOGY_NODE
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "chronology-scope.sh --node" in workflow_text
    assert CHRONOLOGY_NODE not in workflow_text, (
        "test.yml restates the node id instead of taking it from the scope script"
    )
    dagger = DAGGER_MODULE.read_text(encoding="utf-8")
    dagger_literal = re.search(r'CHRONOLOGY_NODE = \(\s*"([^"]+)"\s*"([^"]+)"\s*\)', dagger)
    assert dagger_literal is not None, "ci/dagger main.py no longer names CHRONOLOGY_NODE"
    assert dagger_literal.group(1) + dagger_literal.group(2) == CHRONOLOGY_NODE
    gate_a = GATE_A_SCRIPT.read_text(encoding="utf-8")
    assert f'CHRONOLOGY_NODE="{CHRONOLOGY_NODE}"' in gate_a
    # The witness matches the junit ``name`` attribute, which is the bare
    # function name -- so that name must be what the node id ends in.
    node_name = CHRONOLOGY_NODE.rsplit("::", 1)[1]
    assert 'name=\\"${CHRONOLOGY_NODE##*::}\\"' in gate_a
    assert node_name.startswith("test_")


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch", "", "unknown_event"])
def test_non_pull_request_events_always_retain_the_node(event: str) -> None:
    assert _scope(env={"GITHUB_EVENT_NAME": event}) == "chronology=true"


def test_pull_request_without_a_base_fails_closed() -> None:
    assert _scope(env={"GITHUB_EVENT_NAME": "pull_request"}) == "chronology=true"


def test_force_overrides_every_scope() -> None:
    assert _scope(env={"GITHUB_EVENT_NAME": "push", "CHRONOLOGY_FORCE": "false"}) == "chronology=false"
    assert _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_FORCE": "true"}) == "chronology=true"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    ).stdout.strip()


@pytest.fixture
def pr_repo(tmp_path: Path) -> tuple[Path, str]:
    """A tiny repo with a base commit and one PR commit; returns (repo, base sha)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    return repo, base


def test_pull_request_touching_only_prose_deselects_the_node(pr_repo: tuple[Path, str]) -> None:
    repo, base = pr_repo
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "prose")
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=false"


def test_pull_request_touching_an_input_retains_the_node(pr_repo: tuple[Path, str]) -> None:
    repo, base = pr_repo
    target = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "conformance" / "outside_agent_core.py"
    target.parent.mkdir(parents=True)
    target.write_text("# touched\n", encoding="utf-8")
    _git(repo, "add", str(target))
    _git(repo, "commit", "-q", "-m", "touch an input")
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


def test_pull_request_with_an_unresolvable_base_fails_closed(pr_repo: tuple[Path, str]) -> None:
    repo, _base = pr_repo
    out = _scope(
        env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": "0" * 40},
        cwd=repo,
    )
    assert out == "chronology=true"


def test_workflows_retain_the_node_on_main_nightly_and_release() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert "main" in [str(b) for b in triggers["push"]["branches"]]
    assert triggers["schedule"], "the nightly backstop is gone"
    assert triggers["workflow_dispatch"]["inputs"]["chronology"]["default"] is True
    # Every job that runs the node decides its scope with the same script and
    # feeds the decision to the runner it drives.
    jobs = workflow["jobs"]
    for job in ("offload", "pytest", "cleanroom"):
        runs = [step.get("run", "") for step in jobs[job]["steps"]]
        assert any("ci/chronology-scope.sh >> \"$GITHUB_OUTPUT\"" in run for run in runs), job
    offload = next(s for s in jobs["offload"]["steps"] if "dagger-offload" in s.get("uses", ""))
    assert offload["env"]["CHRONOLOGY"] == "${{ steps.scope.outputs.chronology }}"
    cleanroom = next(s for s in jobs["cleanroom"]["steps"] if s.get("run") == "bash scripts/gate_a_cleanroom.sh")
    assert "steps.scope.outputs.chronology == 'false'" in cleanroom["env"]["GATE_A_DESELECT_CHRONOLOGY"]
    # The release workflow deselects only on pull_request; a tag runs everything.
    publish = yaml.safe_load(PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8"))
    gate_a = next(
        s for s in publish["jobs"]["build"]["steps"]
        if "bash phase-loop-runtime/scripts/gate_a_cleanroom.sh" in s.get("run", "")
    )
    deselect = gate_a["env"]["GATE_A_DESELECT_CHRONOLOGY"]
    assert "github.event_name == 'pull_request'" in deselect and deselect.endswith("|| '0' }}")
