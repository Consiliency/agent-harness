"""Static contract for the CI chronology-node scope (``ci/chronology-scope.sh``).

The heavy CONFORM chronology node (~50 min, ~88 % of a per-PR CI run's wall
clock) proves a property of frozen HISTORY, not of the diff under review, so a
pull request DEFERS it to the landing push: it is retained on every push to
main, on the nightly schedule, and on a pull request only when the diff touches
the gate's own selection plumbing (the script's table). This module pins the
three properties that make that scoping safe:

* the plumbing table is the selection consumers (`ci/` as a whole, an intentional
  fail-closed over-approximation: every file there is CI plumbing) -- the scope script,
  the workflows, the offload/Dagger plumbing, the witness, Gate A's consumer
  and probe -- so it can neither drift wider (re-running the node on ordinary
  PRs) nor narrower (letting a plumbing change skip its own proof);
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


GATE_PLUMBING = (
    "ci/chronology-scope.sh",
    "ci/offload-gate.sh",
    "ci/main-red.sh",
    "ci/gate_metrics.py",
    "ci/dagger/src/agent_harness_ci/main.py",
    ".github/workflows/test.yml",
    ".github/workflows/publish-pypi.yml",
    "phase-loop-runtime/scripts/chronology_witness.py",
    "phase-loop-runtime/scripts/gate_a_cleanroom.sh",
    "phase-loop-runtime/scripts/_gate_a_probe.py",
)
NOT_PLUMBING = (
    "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_core.py",
    "phase-loop-runtime/tests/test_unrelated.py",
    "phase-loop-runtime/tests/conftest.py",
    "phase-loop-runtime/tests/_outside_agent_canonical.py",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/PROVENANCE.json",
    "phase-loop-runtime/scripts/regenerate_skills_bundle.py",
    "phase-loop-runtime/scripts/sync_skills_bundle.py",
    "phase-loop-runtime/MANIFEST.in",
    ".github/workflows/lint.yml",
    "README.md",
    "docs/agent-phase-convergence.md",
)


def test_gate_plumbing_table_is_the_selection_consumers_and_nothing_wider() -> None:
    """The table retains the selection plumbing and nothing else.

    Positives are every file that decides, runs, or witnesses the node; a PR
    editing one could change WHETHER the node runs, so the node must run on
    that PR. Negatives are the runtime, its tests and corpus, non-plumbing
    scripts and prose: those PRs defer the node to the landing push.
    """
    misses = sorted(path for path in GATE_PLUMBING if _scope("--match", path) != "match")
    assert not misses, f"gate plumbing the scope script would let a PR skip: {misses}"
    leaks = sorted(path for path in NOT_PLUMBING if _scope("--match", path) != "no-match")
    assert not leaks, f"non-plumbing paths that would re-run the node on an ordinary PR: {leaks}"
    # Every plumbing positive that is a real file exists (the table is not
    # retaining ghosts) -- except the ones this very PR introduces.
    missing = sorted(p for p in GATE_PLUMBING if not (REPO_ROOT / p).exists())
    assert not missing, f"gate plumbing table names files that do not exist: {missing}"


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


def test_pull_request_touching_gate_plumbing_retains_the_node(pr_repo: tuple[Path, str]) -> None:
    repo, base = pr_repo
    target = repo / "ci" / "offload-gate.sh"
    target.parent.mkdir(parents=True)
    target.write_text("# touched\n", encoding="utf-8")
    _git(repo, "add", str(target))
    _git(repo, "commit", "-q", "-m", "touch gate plumbing")
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


def test_pull_request_renaming_plumbing_out_of_the_table_retains_the_node(
    pr_repo: tuple[Path, str],
) -> None:
    """Rename detection would report only the destination; the old endpoint must count."""
    repo, _ = pr_repo
    src = repo / "ci" / "offload-gate.sh"
    src.parent.mkdir(parents=True)
    src.write_text("# a plumbing script large enough for rename detection\n" * 20, encoding="utf-8")
    _git(repo, "add", str(src))
    _git(repo, "commit", "-q", "-m", "add plumbing")
    base = _git(repo, "rev-parse", "HEAD")
    dest = repo / "tools" / "elsewhere.sh"
    dest.parent.mkdir()
    _git(repo, "mv", str(src), str(dest))
    _git(repo, "commit", "-q", "-m", "move it out of the table")
    assert _scope("--match", "tools/elsewhere.sh") == "no-match"
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


def test_pull_request_touching_gate_a_plumbing_retains_the_node(pr_repo: tuple[Path, str]) -> None:
    repo, base = pr_repo
    script = repo / "phase-loop-runtime" / "scripts" / "gate_a_cleanroom.sh"
    script.parent.mkdir(parents=True)
    script.write_text("# touched\n", encoding="utf-8")
    _git(repo, "add", str(script))
    _git(repo, "commit", "-q", "-m", "touch Gate A plumbing")
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=true"


def test_pull_request_touching_only_the_runtime_defers_the_node(pr_repo: tuple[Path, str]) -> None:
    """The runtime, its tests and the frozen corpus are NOT plumbing: the landing push proves them."""
    repo, base = pr_repo
    for rel in (
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_core.py",
        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
        "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/x.json",
        "phase-loop-runtime/scripts/regenerate_skills_bundle.py",
    ):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# touched\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "touch the runtime only")
    out = _scope(env={"GITHUB_EVENT_NAME": "pull_request", "CHRONOLOGY_BASE_SHA": base}, cwd=repo)
    assert out == "chronology=false"


@pytest.mark.parametrize("name", ["test_\u00e9.py", "test_a\nb.py", 'test_"q".py', "test_a\tb.py"])
def test_pull_request_touching_a_quoted_pathname_retains_the_node(pr_repo: tuple[Path, str], name: str) -> None:
    # Default core.quotePath renders these as "..." with octal escapes in
    # line-oriented output; the scope script must still see the prefix.
    repo, base = pr_repo
    target = repo / "ci" / name
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
    # Only pull_request runs share a group (and cancel each other). Every other
    # event's group carries its own run_id, so a manual chronology=false dispatch
    # on main can neither cancel the landing push run nor replace it while it is
    # still pending in the queue.
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    group = concurrency["group"]
    assert group.startswith("${{ github.event_name == 'pull_request' && ")
    assert "github.event.pull_request.number" in group
    assert group.endswith("|| format('test-{0}-{1}', github.ref, github.run_id) }}")
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
    # A red landing push is reported, never silently absorbed: the main-red job
    # runs after the gate on main pushes and the nightly, in both outcomes, with
    # the issue-writing permission the reporter needs and without gating anything.
    main_red = jobs["main-red"]
    assert main_red["needs"] == "gate"
    condition = " ".join(main_red["if"].split())
    assert condition.startswith("always()")
    assert "github.event_name == 'push' || github.event_name == 'schedule'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "needs.gate.result == 'failure' || needs.gate.result == 'success'" in condition
    assert main_red["permissions"] == {"contents": "read", "actions": "read", "issues": "write"}
    # Per-head group: a shared group lets a late older-head run evict the tip's pending reporter.
    assert main_red["concurrency"] == {"group": "main-red-${{ github.sha }}", "cancel-in-progress": False}
    checkout = next(s for s in main_red["steps"] if "actions/checkout" in s.get("uses", ""))
    assert checkout["with"]["fetch-depth"] == 0, "the reporter's merge range needs full history"
    report = next(s for s in main_red["steps"] if s.get("run") == "bash ci/main-red.sh")
    assert report["env"]["GATE_RESULT"] == "${{ needs.gate.result }}"
    assert report["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "main-red" not in (jobs["gate"].get("needs") or []), "the reporter must never gate"
