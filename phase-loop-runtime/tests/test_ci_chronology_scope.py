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
import sys
from pathlib import Path

import pytest
import yaml

from _outside_agent_canonical import CONFORM_MUTATION_DEFINITIONS, FIXTURE_ROOT, MANIFEST_PATH


REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPE_SCRIPT = REPO_ROOT / "ci" / "chronology-scope.sh"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
PUBLISH_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "publish-pypi.yml"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"
GATE_A_SCRIPT = REPO_ROOT / "phase-loop-runtime" / "scripts" / "gate_a_cleanroom.sh"
WITNESS_SCRIPT = REPO_ROOT / "phase-loop-runtime" / "scripts" / "chronology_witness.py"

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
    # The target tests read the digest-pinned fixture vectors directly; a PR that
    # re-pins a vector (bytes + digest together) must retain the node.
    inputs.add(str(FIXTURE_ROOT.relative_to(REPO_ROOT) / "PROVENANCE.json"))
    inputs.add(str(MANIFEST_PATH.relative_to(REPO_ROOT)))
    assert inputs, "the frozen corpus names no inputs -- the fixture is broken"
    misses = sorted(path for path in inputs if _scope("--match", path) != "match")
    assert not misses, f"chronology inputs the scope script would let a PR skip: {misses}"
    # A negative control: prose cannot change what the node computes.
    assert _scope("--match", "README.md") == "no-match"
    assert _scope("--match", "docs/agent-phase-convergence.md") == "no-match"
    # The whole runtime package directory retains: the proof's process executes
    # inside it, and its packaging inputs (MANIFEST.in, README.md, protocol/) are
    # corpus-pinned package inputs, not prose.
    assert _scope("--match", "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py") == "match"
    assert _scope("--match", "phase-loop-runtime/tests/_dotfiles_tree.py") == "match"
    assert _scope("--match", "phase-loop-runtime/tests/test_unrelated.py") == "match"
    assert _scope("--match", "phase-loop-runtime/MANIFEST.in") == "match"
    assert _scope("--match", "phase-loop-runtime/README.md") == "match"
    assert _scope("--match", "phase-loop-runtime/protocol/protocol.md") == "match"


def test_every_conftest_bootstrapped_plugin_is_a_chronology_input() -> None:
    """conftest.py loads plugins before any test runs; their modules are inputs too."""
    conftest = (REPO_ROOT / "phase-loop-runtime" / "tests" / "conftest.py").read_text(encoding="utf-8")
    modules = sorted(set(re.findall(r'"phase_loop_runtime\.([A-Za-z0-9_.]+):[A-Za-z0-9_]+"', conftest)))
    assert modules, "conftest.py names no bootstrapped plugin -- the probe is broken"
    misses = sorted(
        module
        for module in modules
        if _scope("--match", "phase-loop-runtime/src/phase_loop_runtime/" + module.replace(".", "/") + ".py")
        != "match"
    )
    assert not misses, f"conftest-bootstrapped plugin modules the scope script would let a PR skip: {misses}"


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
    # Every consumer proves its decision through the ONE witness script (which
    # binds module + name and rejects skipped rows); none greps the junit itself.
    witness_call = 'chronology_witness.py'
    for label, text in (("test.yml", workflow_text), ("dagger", dagger), ("gate_a", gate_a)):
        assert witness_call in text, f"{label} no longer runs the shared chronology witness"
        assert 'name=\\"' not in text and "name=\\\\\"" not in text, (
            f"{label} still greps the junit name attribute instead of using the witness"
        )


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


def test_pull_request_renaming_an_input_out_of_the_table_retains_the_node(
    pr_repo: tuple[Path, str],
) -> None:
    """Rename detection would report only the destination; the old endpoint must count."""
    repo, _ = pr_repo
    src = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "conformance" / "outside_agent_core.py"
    src.parent.mkdir(parents=True)
    src.write_text("# a conformance module large enough for rename detection\n" * 20, encoding="utf-8")
    _git(repo, "add", str(src))
    _git(repo, "commit", "-q", "-m", "add an input")
    base = _git(repo, "rev-parse", "HEAD")
    dest = repo / "tools" / "elsewhere.py"
    dest.parent.mkdir()
    _git(repo, "mv", str(src), str(dest))
    _git(repo, "commit", "-q", "-m", "move it out of the table")
    assert _scope("--match", "tools/elsewhere.py") == "no-match"
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


def test_pull_request_touching_a_fixture_vector_retains_the_node(pr_repo: tuple[Path, str]) -> None:
    repo, base = pr_repo
    vector = repo / "phase-loop-runtime" / "tests" / "fixtures" / "outside_agent_contract_v0_2_1" / "x.json"
    vector.parent.mkdir(parents=True)
    vector.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", str(vector))
    _git(repo, "commit", "-q", "-m", "touch a fixture")
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


@pytest.mark.parametrize("name", ["test_\u00e9.py", "test_a\nb.py", 'test_"q".py', "test_a\tb.py"])
def test_pull_request_touching_a_quoted_pathname_retains_the_node(pr_repo: tuple[Path, str], name: str) -> None:
    # Default core.quotePath renders these as "..." with octal escapes in
    # line-oriented output; the scope script must still see the prefix.
    repo, base = pr_repo
    target = repo / "phase-loop-runtime" / "tests" / name
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "quoted path")
    assert _git(repo, "diff", "--name-only", f"{base}...HEAD").startswith('"'), "git did not quote the path"
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


def _witness(junit: Path, expect: str, node: str = CHRONOLOGY_NODE) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(WITNESS_SCRIPT), "--junit", str(junit), "--node", node, "--expect", expect],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def _junit(tmp_path: Path, *cases: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(cases)
        + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


_MODULE = "tests.test_outside_agent_conform_evidence"
_NAME = CHRONOLOGY_NODE.rsplit("::", 1)[1]


def test_witness_present_requires_the_node_to_have_run_and_passed(tmp_path: Path) -> None:
    passed = _junit(tmp_path, f'<testcase classname="{_MODULE}" name="{_NAME}" time="1.0" />')
    assert _witness(passed, "present")[0] == 0
    assert _witness(passed, "absent")[0] == 1
    for tag in ("skipped", "failure", "error"):
        junit = _junit(tmp_path, f'<testcase classname="{_MODULE}" name="{_NAME}"><{tag} message="x"/></testcase>')
        rc, out = _witness(junit, "present")
        assert rc == 1 and f"found it {tag}" in out, (tag, out)
        # A row that did not pass is not "absent" either: a deselect must not be
        # proven by a skip.
        assert _witness(junit, "absent")[0] == 1


def test_witness_absent_requires_no_row_for_the_node(tmp_path: Path) -> None:
    empty = _junit(tmp_path, f'<testcase classname="{_MODULE}" name="test_conform_red_assertion_catalog_is_literal" />')
    assert _witness(empty, "absent")[0] == 0
    assert _witness(empty, "present")[0] == 1
    # Same function name in another module, or a parametrized variant, is not the node.
    foreign = _junit(tmp_path, f'<testcase classname="tests.test_other_module" name="{_NAME}" />')
    assert _witness(foreign, "absent")[0] == 0
    variant = _junit(tmp_path, f'<testcase classname="{_MODULE}" name="{_NAME}[x]" />')
    assert _witness(variant, "absent")[0] == 0
    # The module is bound by whole dotted components: a classname whose tail merely
    # ends with the same characters (``notests.<module>``) is a different module,
    # while a rootdir-prefixed classname (``<pkg>.tests.<module>``) is the node.
    suffix_collision = _junit(tmp_path, f'<testcase classname="tests.no{_MODULE}" name="{_NAME}" />')
    assert _witness(suffix_collision, "absent")[0] == 0
    prefixed = _junit(tmp_path, f'<testcase classname="phase-loop-runtime.{_MODULE}" name="{_NAME}" />')
    assert _witness(prefixed, "present")[0] == 0
    # Only the two roots pytest can emit are the node; a same-named test under a
    # foreign root does not stand in for it.
    shadow = _junit(tmp_path, f'<testcase classname="shadow.{_MODULE}" name="{_NAME}" />')
    assert _witness(shadow, "absent")[0] == 0
    assert _witness(shadow, "present")[0] == 1


def test_witness_refuses_missing_or_malformed_junit(tmp_path: Path) -> None:
    assert _witness(tmp_path / "nope.xml", "absent")[0] == 2
    broken = tmp_path / "broken.xml"
    broken.write_text("<testsuites><testcase", encoding="utf-8")
    assert _witness(broken, "absent")[0] == 2
    assert _witness(_junit(tmp_path), "absent", node="no-separator")[0] == 2


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
    # Only pull_request runs cancel each other: a manual chronology=false dispatch
    # on main queues behind the landing push run instead of cancelling its proof.
    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
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
