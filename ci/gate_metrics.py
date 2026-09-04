#!/usr/bin/env python3
"""Per-PR gate metrics: wall clock, re-executions, and whether the PR retained the
chronology node (touched gate plumbing per ci/chronology-scope.sh --match).

The split-PR-gate change (Consiliency/agent-harness#746) was justified by a
measurement, not a projection; this is the instrument that keeps that
measurement repeatable after landing:

    python3 ci/gate_metrics.py --last 10
    python3 ci/gate_metrics.py --pr 741 --pr 749

One line per PR, then a summary. A PR whose head has no test.yml run (closed
without CI, or the run was pruned) prints `minutes=- executions=0 reruns=-` and
is excluded from the median and the retained share. Exit 2 when `gh` is missing
or not authenticated. `rows()` is pure so the join logic is unit-testable
without GitHub.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCOPE_SCRIPT = Path(__file__).resolve().parent / "chronology-scope.sh"


@dataclass(frozen=True)
class Row:
    number: int
    head: str
    title: str
    minutes: float | None  # None when no run matched the head
    executions: int  # sum of attempts over runs on the head; 0 when no run
    plumbing: bool  # the PR touched a path in the scope script's table

    @property
    def reruns(self) -> int | None:
        return None if self.minutes is None else self.executions - 1

    def line(self) -> str:
        minutes = "-" if self.minutes is None else f"{self.minutes:.1f}"
        reruns = "-" if self.reruns is None else str(self.reruns)
        retained = "yes" if self.plumbing else "no"
        return (
            f"#{self.number} {self.head[:10]} minutes={minutes} "
            f"executions={self.executions} reruns={reruns} retained={retained} {self.title}"
        )


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rows(
    prs: Iterable[dict],
    runs_for: Callable[[dict], Sequence[dict]],
    plumbing_for: Callable[[dict], bool],
) -> list[Row]:
    """Join each PR with the test.yml runs on its head commit.

    `runs_for(pr)` returns run dicts with `headSha`, `attempt`, `startedAt`,
    `updatedAt`; only runs whose `headSha` equals the PR's `headRefOid` count,
    so a run on a superseded head never pollutes the PR's numbers. Minutes come
    from the NEWEST matching run (the one whose verdict stands), executions are
    the summed attempts across all matching runs.
    """
    out: list[Row] = []
    for pr in prs:
        head = pr["headRefOid"]
        matching = [r for r in runs_for(pr) if r.get("headSha") == head]
        if matching:
            newest = max(matching, key=lambda r: _parse_ts(r["startedAt"]))
            minutes = (
                _parse_ts(newest["updatedAt"]) - _parse_ts(newest["startedAt"])
            ).total_seconds() / 60
            executions = sum(int(r.get("attempt") or 1) for r in matching)
        else:
            minutes, executions = None, 0
        out.append(
            Row(
                number=int(pr["number"]),
                head=head,
                title=str(pr.get("title", "")),
                minutes=minutes,
                executions=executions,
                plumbing=bool(plumbing_for(pr)),
            )
        )
    return out


def summary(table: Sequence[Row]) -> str:
    measured = [r for r in table if r.minutes is not None]
    if not measured:
        return f"{len(table)} PRs, none with a run on its head"
    median = statistics.median(r.minutes for r in measured if r.minutes is not None)
    retained = sum(1 for r in measured if r.plumbing)
    reruns = sum(r.reruns or 0 for r in measured)
    return (
        f"{len(measured)}/{len(table)} PRs measured: median minutes={median:.1f} "
        f"retained share={retained}/{len(measured)} reruns total={reruns}"
    )


# ---- gh-backed sources ---------------------------------------------------------


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _gh_json(*args: str):
    return json.loads(_gh(*args) or "null")


def _prs(last: int, numbers: Sequence[int]) -> list[dict]:
    fields = "number,title,headRefOid,headRefName"
    if numbers:
        return [_gh_json("pr", "view", str(n), "--json", fields) for n in numbers]
    return _gh_json(
        "pr", "list", "--state", "all", "--limit", str(last), "--json", fields
    )


def _runs_for(pr: dict) -> list[dict]:
    return _gh_json(
        "run", "list", "--workflow", "test.yml", "--event", "pull_request",
        "--branch", pr["headRefName"], "--limit", "50",
        "--json", "headSha,attempt,startedAt,updatedAt,conclusion",
    )


def _pr_paths(number: int) -> list[str]:
    """Every path a PR touches, on BOTH sides of a rename.

    `gh pr view --json files` reports only the destination `path`, so a PR that
    renames a plumbing file OUT of the table would read as non-plumbing here
    while the gate (which diffs with `--no-renames`) retains the node. The REST
    endpoint carries `previous_filename` for renames; `--paginate` covers PRs
    over the 30-file page.
    """
    entries = _gh_json(
        "api", f"repos/{{owner}}/{{repo}}/pulls/{number}/files", "--paginate", "--slurp",
    )
    paths: list[str] = []
    for page in entries or []:
        for entry in page or []:
            for key in ("filename", "previous_filename"):
                value = entry.get(key)
                if value:
                    paths.append(value)
    return paths


def _plumbing_for(pr: dict) -> bool:
    for path in _pr_paths(int(pr["number"])):
        verdict = subprocess.run(
            ["bash", str(SCOPE_SCRIPT), "--match", path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if verdict == "match":
            return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--last", type=int, default=10, help="most recent N PRs (any state)")
    parser.add_argument("--pr", type=int, action="append", default=[], help="specific PR number (repeatable)")
    args = parser.parse_args(argv)

    if shutil.which("gh") is None:
        print("gate_metrics: `gh` is not installed", file=sys.stderr)
        return 2
    auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if auth.returncode != 0:
        print("gate_metrics: `gh auth status` failed; authenticate first", file=sys.stderr)
        return 2

    table = rows(_prs(args.last, args.pr), _runs_for, _plumbing_for)
    for row in table:
        print(row.line())
    print(summary(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
