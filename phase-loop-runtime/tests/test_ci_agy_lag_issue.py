"""`ci/agy-lag-issue.sh`: the agy-lag issue follows the lag report (ROLLJOB-detail §5.2, EC-ROLLJOB-7).

The script runs against a fake ``gh`` on ``PATH`` that keeps the issues in a JSON file, so
nothing reaches GitHub.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ci" / "agy-lag-issue.sh"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file() or shutil.which("bash") is None,
                                reason="the script is repository source and needs bash")

FAKE_GH = r'''#!PYTHON
import json, os, sys
state_path, log_path = os.environ["FAKE_GH_STATE"], os.environ["FAKE_GH_LOG"]
state = json.load(open(state_path))
argv = sys.argv[1:]
with open(log_path, "a") as log:
    log.write(json.dumps(argv) + "\n")
def opt(name):
    return argv[argv.index(name) + 1]
if state.get("fail_list") and argv[:2] == ["issue", "list"]:
    sys.exit(1)
if argv[:2] == ["issue", "list"]:
    assert opt("--label") == "agy-lag" and opt("--state") == "open"
    print(json.dumps([{"number": i["number"]} for i in state["issues"]
                      if i["state"] == "open" and "agy-lag" in i["labels"]]))
elif argv[:2] == ["issue", "create"]:
    number = max([i["number"] for i in state["issues"]] + [100]) + 1
    state["issues"].append({"number": number, "state": "open", "labels": [opt("--label")],
                            "title": opt("--title"), "comments": [opt("--body")]})
    print(f"https://github.com/x/y/issues/{number}")
elif argv[:2] in (["issue", "comment"], ["issue", "close"]):
    issue = next(i for i in state["issues"] if i["number"] == int(argv[2]))
    issue["comments"].append(opt("--body") if argv[1] == "comment" else opt("--comment"))
    if argv[1] == "close":
        issue["state"] = "closed"
elif argv[:2] == ["label", "create"]:
    pass
else:
    sys.exit(f"unexpected gh call {argv}")
json.dump(state, open(state_path, "w"))
'''


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH.replace("PYTHON", sys.executable))
        gh.chmod(0o755)
        self.state_path, self.log = tmp_path / "state.json", tmp_path / "gh.log"
        self.report = tmp_path / "agy-lag-report.json"
        self.save({"issues": []})

    def save(self, state):
        self.state_path.write_text(json.dumps(state))

    def state(self):
        return json.loads(self.state_path.read_text())

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def mutations(self):
        return [c for c in self.calls() if c[:2] in (["issue", "create"], ["issue", "comment"], ["issue", "close"],
                                                     ["label", "create"])]

    def open_issues(self):
        return [i["number"] for i in self.state()["issues"] if i["state"] == "open"]

    def write_report(self, status, *, enforced, release="9.9.9"):
        self.report.write_text(json.dumps({"latest_release": release, "lag": {
            "status": status, "enforced": enforced, "release": release, "published_at": "2026-11-01T00:00:00Z",
            "bound_s": 172800, "in_flight": []}, "headroom": {}}))

    def run(self):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "AGY_LAG_REPORT": str(self.report), "GITHUB_RUN_ID": "123",
               "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "Consiliency/agent-harness",
               "GH_TOKEN": "ghs_fake", "FAKE_GH_STATE": str(self.state_path), "FAKE_GH_LOG": str(self.log),
               "HOME": str(self.tmp)}
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def _issue(number, state="open"):
    return {"number": number, "state": state, "labels": ["agy-lag"], "title": "agy catalog lag", "comments": []}


def test_no_report_changes_nothing(world):
    assert world.run().returncode == 0 and world.calls() == []


def test_an_unreadable_report_changes_nothing(world):
    world.report.write_text("{not json")
    assert world.run().returncode == 0 and world.calls() == []


@pytest.mark.parametrize("status", ["fail", "ok", "warn_inside_bound", "warn_pr_open"])
def test_report_only_never_creates_comments_on_or_closes_an_issue(world, status):
    world.save({"issues": [_issue(7), _issue(8)]})
    world.write_report(status, enforced=False)
    done = world.run()
    assert done.returncode == 0, done.stderr
    assert world.calls() == [] and world.open_issues() == [7, 8]


def test_two_failing_enforced_runs_leave_exactly_one_open_issue(world):
    world.write_report("fail", enforced=True)
    assert world.run().returncode == 0
    (created,) = world.open_issues()
    assert world.run().returncode == 0
    assert world.open_issues() == [created]
    issue = world.state()["issues"][0]
    assert len(issue["comments"]) == 2 and "9.9.9" in issue["comments"][-1]
    assert [c[:2] for c in world.mutations()] == [["label", "create"], ["issue", "create"], ["issue", "comment"]]


def test_a_failing_enforced_run_comments_on_the_lowest_and_closes_duplicates(world):
    world.save({"issues": [_issue(30), _issue(12), _issue(20), _issue(5, state="closed")]})
    world.write_report("fail", enforced=True)
    assert world.run().returncode == 0
    assert world.open_issues() == [12]
    by_number = {i["number"]: i for i in world.state()["issues"]}
    assert len(by_number[12]["comments"]) == 1 and "9.9.9" in by_number[12]["comments"][0]
    assert all("Duplicate" in by_number[n]["comments"][-1] for n in (20, 30))


@pytest.mark.parametrize("status", ["ok", "warn_inside_bound", "warn_pr_open"])
def test_a_passing_enforced_run_closes_every_open_issue(world, status):
    world.save({"issues": [_issue(3), _issue(4)]})
    world.write_report(status, enforced=True)
    assert world.run().returncode == 0
    assert world.open_issues() == [] and not [c for c in world.calls() if c[:2] == ["issue", "create"]]


def test_a_passing_enforced_run_with_no_issue_changes_nothing(world):
    world.write_report("ok", enforced=True)
    assert world.run().returncode == 0 and world.mutations() == []


def test_a_listing_failure_stops_without_creating_an_issue(world):
    state = world.state()
    state["fail_list"] = True
    world.save(state)
    world.write_report("fail", enforced=True)
    assert world.run().returncode != 0
    assert world.mutations() == []


def test_the_token_is_never_on_a_command_line(world):
    world.write_report("fail", enforced=True)
    world.run()
    assert not any("ghs_fake" in part for call in world.calls() for part in call)


def test_the_script_is_executable_and_strict():
    text = SCRIPT.read_text()
    assert os.access(SCRIPT, os.X_OK) and "set -euo pipefail" in text
    assert "--jq" not in text  # parses with python3, so a fake gh needs no jq
