"""`verify_qualified_agy_image.py --route-core` (agent-harness#1029).

Pull requests check only the qualified route's core files; the full pin set is enforced at
release. These pin both directions: a non-core drift passes route-core but still fails the
full check, and a route-core drift fails route-core.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
SCOPE = Path(__file__).resolve().parents[1] / "scripts" / "agy_full_pin_scope.sh"
REPO = Path(__file__).resolve().parents[2]
RECORDS = REPO / "plans" / "evidence" / "qualified-provider-images.json"
PUBLISH = REPO / ".github" / "workflows" / "publish-pypi.yml"
QUALIFIED = REPO / ".github" / "workflows" / "qualified-agy-image.yml"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or not RECORDS.is_file(),
    reason="the verifier and its evidence are repository source, absent from the standalone layout",
)


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _drift(verifier, monkeypatch, name):
    record, _ = verifier.validate_record(verify_sources=False)
    drifted = dict(record["source_sha256"])
    drifted[name] = "0" * 64
    monkeypatch.setattr(verifier, "actual_source_hashes", lambda: drifted)


def test_the_route_core_is_pinned_by_the_record(verifier):
    record, _ = verifier.validate_record(verify_sources=False)
    assert set(verifier.ROUTE_CORE) <= set(record["source_sha256"])


def _non_core(verifier):
    record, _ = verifier.validate_record(verify_sources=False)
    return next(name for name in sorted(record["source_sha256"]) if name not in verifier.ROUTE_CORE)


def test_a_non_core_drift_passes_route_core_but_fails_the_release_check(verifier, monkeypatch):
    _drift(verifier, monkeypatch, _non_core(verifier))
    verifier.validate_record(route_core_only=True)
    with pytest.raises(ValueError, match="differ from this checkout"):
        verifier.validate_record()


@pytest.mark.parametrize("name", ["gemini_heartbeat.py", "qualify_gemini_heartbeat.py"])
def test_a_route_core_drift_fails_route_core(verifier, monkeypatch, name):
    _drift(verifier, monkeypatch, name)
    with pytest.raises(ValueError, match=f"route-core file {name}"):
        verifier.validate_record(route_core_only=True)


def test_a_route_core_file_missing_from_the_record_fails(verifier, monkeypatch):
    record, _ = verifier.validate_record(verify_sources=False)
    monkeypatch.setattr(verifier, "actual_source_hashes", lambda: dict(record["source_sha256"]))
    monkeypatch.setattr(verifier, "ROUTE_CORE", verifier.ROUTE_CORE + ("not_pinned.py",))
    with pytest.raises(ValueError, match="does not pin route-core file not_pinned.py"):
        verifier.validate_record(route_core_only=True)


def test_publication_is_gated_on_the_full_pin_set():
    steps = yaml.safe_load(PUBLISH.read_text())["jobs"]["build"]["steps"]
    names = [step.get("name", "") for step in steps]
    index = names.index("Verify every agy qualification source pin (release only)")
    step = steps[index]
    assert step["if"] == "github.event_name != 'pull_request'"
    assert step["run"] == "python phase-loop-runtime/scripts/verify_qualified_agy_image.py --source-only"
    assert "continue-on-error" not in step
    assert index < names.index("Build sdist + wheel") < names.index(
        "Gate A — verify the exact prebuilt wheel in a clean room")


def test_every_qualified_image_run_checks_the_route_core():
    step = next(s for s in yaml.safe_load(QUALIFIED.read_text())["jobs"]["verify"]["steps"]
                if s.get("name") == "Verify route-core qualification pins")
    assert "if" not in step and "continue-on-error" not in step


def _git(repo, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], cwd=repo, check=True, capture_output=True)


def _merge_commit(tmp_path, pr_changes):
    """A PR forked before main changed RELEASE_PIN, merged as GitHub's merge ref."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "RELEASE_PIN").write_text("v1\n")
    (repo / "x.py").write_text("a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    for name, text in pr_changes.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pr")
    _git(repo, "checkout", "-q", "main")
    # main advanced AFTER the fork: a release cut, unless the PR itself is one
    advanced = "y.py" if "RELEASE_PIN" in pr_changes else "RELEASE_PIN"
    (repo / advanced).write_text("v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "main advanced")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge ref", "pr")
    return repo


def _rev(repo, ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=repo, capture_output=True, text=True).stdout.strip()


def _scope(repo, event, github_sha=None, pr_head=None):
    """Run the scope script as GitHub would on a pull_request: GITHUB_SHA is the synthetic
    merge commit and PR_HEAD_SHA its second parent (defaults: taken from the repo)."""
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_OUTPUT", "GITHUB_SHA", "PR_HEAD_SHA")}
    env["EVENT"] = event
    if event == "pull_request" and (repo / ".git").exists():
        env["GITHUB_SHA"] = github_sha if github_sha is not None else _rev(repo, "HEAD")
        env["PR_HEAD_SHA"] = pr_head if pr_head is not None else _rev(repo, "HEAD^2")
    return subprocess.run(["bash", str(SCOPE)], cwd=repo, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("changes,full", [
    ({"x.py": "b\n"}, "false"),                           # base moved; the PR did not
    ({"RELEASE_PIN": "v3\n"}, "true"),                    # the PR is a release cut
    ({"plans/evidence/agy-9.9.9-linux-x64-qualification.json": "{}"}, "true"),
])
def test_release_cut_detection_uses_the_prs_own_effect(tmp_path, changes, full):
    """#1032 r1 (codex, claude): a two-dot base..head diff flagged RELEASE_PIN for a PR that
    merely forked before a release cut."""
    result = _scope(_merge_commit(tmp_path, changes), "pull_request")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"full={full}"


def test_release_cut_detection_fails_closed_without_a_base_parent(tmp_path):
    repo = tmp_path / "root"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "RELEASE_PIN").write_text("v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "root")
    result = _scope(repo, "pull_request")
    assert result.returncode == 1 and "synthetic merge commit" in result.stderr


def test_release_cut_detection_refuses_a_non_merge_checkout(tmp_path):
    """agent-harness#1036: on a plain commit HEAD^1 is the previous commit, not the base."""
    repo = tmp_path / "linear"
    repo.mkdir()
    _git(repo, "init", "-q")
    for text in ("v1\n", "v2\n"):
        (repo / "RELEASE_PIN").write_text(text)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", text)
    result = _scope(repo, "pull_request")
    assert result.returncode == 1 and "synthetic merge commit" in result.stderr


def test_the_full_check_step_is_wired_to_the_scope_decision():
    """agent-harness#1036: the full step runs exactly when the scope says so, and blocks."""
    steps = {s.get("name"): s for s in yaml.safe_load(QUALIFIED.read_text())["jobs"]["verify"]["steps"]}
    scope = steps["Decide whether this run needs the full pin set"]
    # Exact key set: a later `if:` or `continue-on-error:` on the scope step would skip or
    # mask the decision while the job stays green (agent-harness#1038).
    assert set(scope) == {"name", "id", "env", "run"}, sorted(scope)
    assert scope["id"] == "full" and scope["run"] == "bash phase-loop-runtime/scripts/agy_full_pin_scope.sh"
    # Without EVENT the case falls through to full=false and the full check never runs.
    assert scope["env"] == {"EVENT": "${{ github.event_name }}",
                            "PR_HEAD_SHA": "${{ github.event.pull_request.head.sha }}"}
    assert "continue-on-error" not in yaml.safe_load(QUALIFIED.read_text())["jobs"]["verify"]
    full = steps["Verify every qualification source pin (release cut, new record, dispatch)"]
    assert set(full) == {"name", "if", "run"}, sorted(full)
    # Order and job-level keys (#1044 r1 claude): the full step must follow the scope
    # step (else steps.full.outputs.full is empty and it silently skips), and the job
    # itself must carry no `if:` (a skipped job reports success) or continue-on-error.
    order = [s.get("name") for s in yaml.safe_load(QUALIFIED.read_text())["jobs"]["verify"]["steps"]]
    assert order.index(scope["name"]) < order.index(full["name"]), order
    job = yaml.safe_load(QUALIFIED.read_text())["jobs"]["verify"]
    assert not {"if", "continue-on-error"} & set(job), sorted(job)
    assert full["if"] == "steps.full.outputs.full == 'true'"
    assert full["run"] == "python phase-loop-runtime/scripts/verify_qualified_agy_image.py --source-only"


@pytest.mark.parametrize("event,full", [("workflow_dispatch", "true"), ("push", "false"), ("schedule", "false")])
def test_other_events(tmp_path, event, full):
    result = _scope(tmp_path, event)
    assert result.returncode == 0 and result.stdout.strip() == f"full={full}"


def test_a_merge_commit_that_is_not_the_pr_merge_ref_fails_closed(tmp_path):
    """#1037 r1 (codex): a merge commit that is not GitHub's synthetic merge for THIS PR --
    HEAD is not $GITHUB_SHA, or HEAD^2 is not the PR head -- must fail closed rather than
    diff against whatever its first parent happens to be. The fixture's merge stands in
    for such a commit; only the exact (GITHUB_SHA, PR_HEAD_SHA) pair is accepted."""
    repo = _merge_commit(tmp_path, {"RELEASE_PIN": "v3\n"})
    merge = _rev(repo, "HEAD")
    assert _scope(repo, "pull_request", github_sha="0" * 40).returncode == 1
    assert _scope(repo, "pull_request", pr_head=_rev(repo, "HEAD^1")).returncode == 1
    ok = _scope(repo, "pull_request", github_sha=merge)
    assert ok.returncode == 0 and ok.stdout.strip() == "full=true"
