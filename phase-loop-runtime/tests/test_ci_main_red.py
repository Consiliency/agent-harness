"""Contract for the main-red reporter (``ci/main-red.sh``).

The reporter turns the suite gate's result on main into ONE labelled issue.
Because pull requests defer the CONFORM chronology node to the landing push
(``ci/chronology-scope.sh``), a regression no PR could see first appears on
main -- this script is what makes that visible. These tests drive the real
script against a ``gh`` stub that keeps issue state in a JSON file and runs the
real ``jq`` behind ``--jq``, so the script's own jq filters are exercised.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ci" / "main-red.sh"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="ci/main-red.sh not in this checkout")

assert shutil.which("jq"), "these tests run the script's jq filters for real; install jq"

_STUB = r'''#!/usr/bin/env python3
"""gh stub: JSON state in $STUB_STATE, every call appended to $STUB_LOG."""
import json, os, subprocess, sys

argv = sys.argv[1:]
state_path, log_path = os.environ["STUB_STATE"], os.environ["STUB_LOG"]
state = json.load(open(state_path))


def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None


def emit(payload):
    text = json.dumps(payload)
    query = opt("--jq")
    if query is not None:
        text = subprocess.run(["jq", "-r", query], input=text, capture_output=True, text=True, check=True).stdout
    sys.stdout.write(text)


entry = {"argv": argv}
body_file = opt("--body-file")
if body_file:
    entry["body"] = open(body_file).read()
open(log_path, "a").write(json.dumps(entry) + "\n")

if argv[0] == "api":
    # A list of tips is consumed one per read: the last one sticks. Lets a test
    # move the tip BETWEEN the up-front check and the pre-mutation re-read.
    tips = state["tip"] if isinstance(state["tip"], list) else [state["tip"]]
    tip = tips.pop(0) if len(tips) > 1 else tips[0]
    state["tip"] = tips
    emit({"commit": {"sha": tip}})
elif argv[:2] == ["label", "create"]:
    pass
elif argv[:2] == ["issue", "list"]:
    wanted = opt("--state")
    issues = [i for i in state["issues"] if wanted == "all" or i["state"] == wanted.upper()]
    if opt("--label"):
        issues = [i for i in issues if opt("--label") in i["labels"]]
    emit(issues[: int(opt("--limit"))])
elif argv[:2] == ["issue", "create"]:
    number = max([i["number"] for i in state["issues"]] + [0]) + 1
    state["issues"].append({"number": number, "state": "OPEN", "labels": [opt("--label")],
                            "body": entry["body"], "comments": []})
    print(f"https://example.invalid/issues/{number}")
elif argv[:2] == ["issue", "view"]:
    issue = next(i for i in state["issues"] if i["number"] == int(argv[2]))
    emit({"body": issue.get("body", ""), "comments": [{"body": c} for c in issue.get("comments", [])]})
elif argv[:2] == ["issue", "comment"]:
    issue = next(i for i in state["issues"] if i["number"] == int(argv[2]))
    issue.setdefault("comments", []).append(entry["body"])
elif argv[:2] in (["issue", "reopen"], ["issue", "close"]):
    number = int(argv[2])
    for issue in state["issues"]:
        if issue["number"] == number:
            issue["state"] = "OPEN" if argv[1] == "reopen" else "CLOSED"
            if opt("--comment"):
                issue.setdefault("comments", []).append(opt("--comment"))
elif argv[:2] == ["run", "list"]:
    emit([{"headSha": state["green"]}] if state.get("green") else [])
elif argv[:2] == ["run", "view"]:
    emit({"jobs": state["jobs"]})
else:
    sys.exit(f"gh stub: unhandled {argv}")
json.dump(state, open(state_path, "w"))
'''


def _git(repo: Path, *args: str) -> str:
    env = {
        "PATH": os.environ["PATH"], "HOME": str(repo),
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    """A main branch: base -> (green) -> merge of a feature -> plain commit. Returns the shas oldest-first."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "base"); shas.append(_git(repo, "rev-parse", "HEAD"))
    (repo / "a.txt").write_text("b\n")
    _git(repo, "commit", "-q", "-am", "green landing"); shas.append(_git(repo, "rev-parse", "HEAD"))
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "f.txt").write_text("f\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "feature work")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature (Consiliency/agent-harness#1)", "feature")
    shas.append(_git(repo, "rev-parse", "HEAD"))
    (repo / "a.txt").write_text("c\n")
    _git(repo, "commit", "-q", "-am", "plain landing"); shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


class Harness:
    def __init__(self, tmp_path: Path, repo: Path) -> None:
        self.repo = repo
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "gh"
        stub.write_text(_STUB)
        stub.chmod(0o755)
        self.state_path = tmp_path / "state.json"
        self.log_path = tmp_path / "calls.log"

    def run(self, *, gate: str, sha: str, tip=None, issues=(), green: str | None = None, jobs=()):
        """`tip` may be a list: successive tip reads consume it, the last sticks."""
        self.state_path.write_text(json.dumps({
            "tip": tip or sha, "issues": list(issues), "green": green,
            "jobs": list(jobs) or [{"name": "gate", "conclusion": "failure"}],
        }))
        self.log_path.write_text("")
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.repo),
            "STUB_STATE": str(self.state_path), "STUB_LOG": str(self.log_path),
            "GATE_RESULT": gate, "GITHUB_RUN_ID": "4242", "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "Consiliency/agent-harness", "GITHUB_SHA": sha, "GH_TOKEN": "stub",
        }
        return subprocess.run(["bash", str(SCRIPT)], cwd=self.repo, env=env, capture_output=True, text=True)

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line]

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def verbs(self) -> list[str]:
        return [" ".join(c["argv"][:2]) for c in self.calls()]

    def issue_states(self) -> dict[int, str]:
        return {i["number"]: i["state"] for i in self.state()["issues"]}


@pytest.fixture
def harness(tmp_path: Path, main_repo: tuple[Path, list[str]]) -> tuple[Harness, list[str]]:
    return Harness(tmp_path, main_repo[0]), main_repo[1]


RUN_URL = "https://github.com/Consiliency/agent-harness/actions/runs/4242"


def test_stale_run_reports_nothing(harness) -> None:
    h, shas = harness
    result = h.run(gate="failure", sha=shas[2], tip=shas[3])
    assert result.returncode == 0, result.stderr
    assert "stale run" in result.stderr
    assert h.verbs() == ["api repos/Consiliency/agent-harness/branches/main"]
    assert h.state()["issues"] == []


def test_failure_with_no_issue_creates_one_with_the_range_and_failing_jobs(harness) -> None:
    h, shas = harness
    result = h.run(
        gate="failure", sha=shas[3], green=shas[1],
        jobs=[{"name": "gate", "conclusion": "failure"}, {"name": "offload", "conclusion": "failure"},
              {"name": "lint", "conclusion": "success"}],
    )
    assert result.returncode == 0, result.stderr
    assert "label create" in h.verbs()
    create = next(c for c in h.calls() if c["argv"][:2] == ["issue", "create"])
    assert create["argv"][create["argv"].index("--label") + 1] == "ci-main-red"
    assert create["argv"][create["argv"].index("--title") + 1] == "suite gate is red on main"
    body = create["body"]
    assert RUN_URL in body and shas[3] in body
    assert "failing jobs: gate, offload" in body
    assert f"Landings since the last green push run ({shas[1]}):" in body
    assert "Merge feature (Consiliency/agent-harness#1)" in body
    assert "plain landing" in body, "a squash/direct landing is a landing too (--first-parent)"
    assert "feature work" not in body, "commits inside a merged branch are not landings"
    assert "green landing" not in body, "the range starts after the last green head"
    assert h.issue_states() == {1: "OPEN"}
    assert f"<!-- main-red head: {shas[3]} -->" in body, "every report stamps its head"


def test_failure_with_an_open_issue_comments_instead_of_creating(harness) -> None:
    h, shas = harness
    existing = [{"number": 7, "state": "OPEN", "labels": ["ci-main-red"]}]
    result = h.run(gate="failure", sha=shas[3], green=shas[1], issues=existing)
    assert result.returncode == 0, result.stderr
    assert "issue create" not in h.verbs()
    comment = next(c for c in h.calls() if c["argv"][:2] == ["issue", "comment"])
    assert comment["argv"][2] == "7" and RUN_URL in comment["body"]
    assert h.issue_states() == {7: "OPEN"}


def test_failure_with_a_closed_issue_reopens_and_comments(harness) -> None:
    h, shas = harness
    result = h.run(gate="failure", sha=shas[3], green=shas[1],
                   issues=[{"number": 7, "state": "CLOSED", "labels": ["ci-main-red"]}])
    assert result.returncode == 0, result.stderr
    verbs = h.verbs()
    assert "issue create" not in verbs
    assert verbs.index("issue reopen") < verbs.index("issue comment")
    assert h.state()["issues"][0]["state"] == "OPEN"


def test_failure_without_a_green_run_falls_back_to_recent_history(harness) -> None:
    h, shas = harness
    result = h.run(gate="failure", sha=shas[3], green=None)
    assert result.returncode == 0, result.stderr
    body = next(c for c in h.calls() if c["argv"][:2] == ["issue", "create"])["body"]
    assert "No green push run found on main; last 20 commits:" in body
    assert "plain landing" in body and "base" in body


def test_success_closes_every_open_issue_with_the_run(harness) -> None:
    h, shas = harness
    result = h.run(gate="success", sha=shas[3], issues=[
        {"number": 3, "state": "OPEN", "labels": ["ci-main-red"]},
        {"number": 5, "state": "CLOSED", "labels": ["ci-main-red"]},
        {"number": 8, "state": "OPEN", "labels": ["ci-main-red"]},
    ])
    assert result.returncode == 0, result.stderr
    closes = [c for c in h.calls() if c["argv"][:2] == ["issue", "close"]]
    assert [c["argv"][2] for c in closes] == ["3", "8"]
    assert all(f"suite gate green again on main: run {RUN_URL}" in " ".join(c["argv"]) for c in closes)
    assert all(f"<!-- main-red head: {shas[3]} -->" in " ".join(c["argv"]) for c in closes), "the close stamps its head"
    assert "issue create" not in h.verbs() and "run list" not in h.verbs()
    assert {i["number"]: i["state"] for i in h.state()["issues"]} == {3: "CLOSED", 5: "CLOSED", 8: "CLOSED"}


def test_success_with_nothing_open_is_a_quiet_no_op(harness) -> None:
    h, shas = harness
    result = h.run(gate="success", sha=shas[3], issues=[{"number": 5, "state": "CLOSED", "labels": ["ci-main-red"]}])
    assert result.returncode == 0, result.stderr
    assert not any(v.startswith("issue close") or v.startswith("issue create") for v in h.verbs())


@pytest.mark.parametrize(("gate", "code"), [("cancelled", 2), ("skipped", 2), ("", 1)])
def test_other_gate_results_exit_nonzero_without_touching_issues(harness, gate: str, code: int) -> None:
    """cancelled/skipped: the script's own exit 2; "": bash's required-env check (exit 1) fires first."""
    h, shas = harness
    result = h.run(gate=gate, sha=shas[3], issues=[{"number": 7, "state": "OPEN", "labels": ["ci-main-red"]}])
    assert result.returncode == code, result.stderr
    assert not any(v.startswith("issue") for v in h.verbs())


def _stamp(sha: str) -> str:
    return f"<!-- main-red head: {sha} -->"


def test_tip_lost_between_the_first_check_and_the_mutation_stops_the_report(harness) -> None:
    """Reporters of different heads run concurrently; the tip is re-read right before
    each mutating call, so a reporter that loses the tip mid-run never creates or closes."""
    h, shas = harness
    # red: the up-front read says tip, the pre-create re-read says a newer head landed
    result = h.run(gate="failure", sha=shas[2], tip=[shas[2], shas[3]], green=shas[1])
    assert result.returncode == 0, result.stderr
    assert "stale run" in result.stderr
    assert "issue create" not in h.verbs() and h.state()["issues"] == []
    # red over an existing issue: the pre-comment / pre-reopen re-read fails
    for state in ("OPEN", "CLOSED"):
        result = h.run(gate="failure", sha=shas[2], tip=[shas[2], shas[3]], green=shas[1],
                       issues=[{"number": 7, "state": state, "labels": ["ci-main-red"]}])
        assert result.returncode == 0, result.stderr
        assert not any(v in ("issue reopen", "issue comment") for v in h.verbs()), state
        assert h.issue_states() == {7: state}
    # green: same shape, the pre-close re-read fails, the open issue is left alone
    result = h.run(gate="success", sha=shas[2], tip=[shas[2], shas[3]],
                   issues=[{"number": 7, "state": "OPEN", "labels": ["ci-main-red"]}])
    assert result.returncode == 0, result.stderr
    assert "issue close" not in h.verbs() and h.issue_states() == {7: "OPEN"}


def test_an_older_head_never_closes_or_reopens_over_a_newer_heads_report(harness) -> None:
    """Every report stamps its head; a reporter touches the issue only when the last
    stamped head is an ancestor of its own. shas[2] is older than shas[3]."""
    h, shas = harness
    newer_open = [{"number": 7, "state": "OPEN", "labels": ["ci-main-red"], "body": _stamp(shas[3])}]
    result = h.run(gate="success", sha=shas[2], issues=newer_open)
    assert result.returncode == 0, result.stderr
    assert "issue close" not in h.verbs() and h.issue_states() == {7: "OPEN"}
    assert "newer head" in result.stderr

    # the stamp in the LAST comment wins over the body
    newer_closed = [{"number": 7, "state": "CLOSED", "labels": ["ci-main-red"],
                     "body": _stamp(shas[1]), "comments": ["green again " + _stamp(shas[3])]}]
    result = h.run(gate="failure", sha=shas[2], green=shas[1], issues=newer_closed)
    assert result.returncode == 0, result.stderr
    assert not any(v in ("issue reopen", "issue comment", "issue create") for v in h.verbs())
    assert h.issue_states() == {7: "CLOSED"}

    # the newer head over an older stamp proceeds (ancestor), and stamps itself
    older_closed = [{"number": 7, "state": "CLOSED", "labels": ["ci-main-red"], "body": _stamp(shas[2])}]
    result = h.run(gate="failure", sha=shas[3], green=shas[1], issues=older_closed)
    assert result.returncode == 0, result.stderr
    assert "issue reopen" in h.verbs() and h.issue_states() == {7: "OPEN"}
    assert _stamp(shas[3]) in h.state()["issues"][0]["comments"][-1]
    # ... and the older head now finds itself behind that stamp
    result = h.run(gate="success", sha=shas[2], issues=h.state()["issues"])
    assert result.returncode == 0, result.stderr
    assert h.issue_states() == {7: "OPEN"}


def test_script_is_executable_and_runs_with_the_bare_container_path() -> None:
    """The offloaded suite's container has only /usr/bin:/bin; the script needs nothing else."""
    assert os.access(SCRIPT, os.X_OK)
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert sys.version_info >= (3, 10)
