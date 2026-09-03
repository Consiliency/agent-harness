"""Pure-join contract for ``ci/gate_metrics.py`` (the per-PR gate instrument)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "ci" / "gate_metrics.py"

pytestmark = pytest.mark.skipif(not MODULE.exists(), reason="ci/gate_metrics.py not in this checkout")


def _load():
    spec = importlib.util.spec_from_file_location("gate_metrics", MODULE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclass field resolution looks the module up by name
    spec.loader.exec_module(mod)
    return mod


def test_rows_join_on_the_head_and_count_every_attempt() -> None:
    gm = _load()
    prs = [
        {"number": 10, "title": "plumbing", "headRefOid": "aaa", "headRefName": "x"},
        {"number": 11, "title": "runtime", "headRefOid": "bbb", "headRefName": "y"},
        {"number": 12, "title": "no run", "headRefOid": "ccc", "headRefName": "z"},
    ]
    runs = {
        "x": [
            # newest run on the head: 10 min, rerun once (attempt 2)
            {"headSha": "aaa", "attempt": 2, "startedAt": "2026-09-03T10:00:00Z", "updatedAt": "2026-09-03T10:10:00Z"},
            # older run on the same head: counted in executions, not in minutes
            {"headSha": "aaa", "attempt": 1, "startedAt": "2026-09-03T09:00:00Z", "updatedAt": "2026-09-03T09:50:00Z"},
            # a superseded head never pollutes the PR's numbers
            {"headSha": "old", "attempt": 1, "startedAt": "2026-09-03T08:00:00Z", "updatedAt": "2026-09-03T08:59:00Z"},
        ],
        "y": [{"headSha": "bbb", "attempt": 1, "startedAt": "2026-09-03T10:00:00Z", "updatedAt": "2026-09-03T10:08:30Z"}],
        "z": [],
    }
    table = gm.rows(prs, lambda pr: runs[pr["headRefName"]], lambda pr: pr["number"] == 10)
    assert [(r.number, r.minutes, r.executions, r.reruns, r.plumbing) for r in table] == [
        (10, 10.0, 3, 2, True),
        (11, 8.5, 1, 0, False),
        (12, None, 0, None, False),
    ]
    assert table[2].line() == "#12 ccc minutes=- executions=0 reruns=- retained=no no run"
    assert table[0].line().startswith("#10 aaa minutes=10.0 executions=3 reruns=2 retained=yes")
    # The no-run PR is excluded from the median (10, 8.5 -> 9.25) and the share.
    assert gm.summary(table) == "2/3 PRs measured: median minutes=9.2 retained share=1/2 reruns total=2"
    assert gm.summary([table[2]]) == "1 PRs, none with a run on its head"


def test_main_exits_2_without_gh_or_without_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gm = _load()
    monkeypatch.setattr(gm.shutil, "which", lambda _name: None)
    assert gm.main(["--last", "1"]) == 2

    monkeypatch.setattr(gm.shutil, "which", lambda _name: "/stub/gh")

    class Failed:
        returncode = 1

    monkeypatch.setattr(gm.subprocess, "run", lambda *a, **k: Failed())
    assert gm.main(["--pr", "1"]) == 2
    assert sys.version_info >= (3, 10)


def test_plumbing_sees_both_sides_of_a_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rename OUT of the plumbing table retains the node at the gate (the scope
    script diffs with --no-renames), so the instrument must read the source side too.
    `gh pr view --json files` only reports the destination; the REST files endpoint
    carries `previous_filename`."""
    gm = _load()
    calls: list[tuple[str, ...]] = []

    def fake_gh_json(*args: str):
        calls.append(args)
        assert args[:2] == ("api", "repos/{owner}/{repo}/pulls/7/files")
        assert "--paginate" in args
        # two pages: a docs-only edit, then a plumbing file renamed out of ci/
        return [
            [{"filename": "docs/x.md", "status": "modified"}],
            [{"filename": "tools/moved.sh", "previous_filename": "ci/moved.sh", "status": "renamed"}],
        ]

    monkeypatch.setattr(gm, "_gh_json", fake_gh_json)
    assert gm._pr_paths(7) == ["docs/x.md", "tools/moved.sh", "ci/moved.sh"]
    assert gm._plumbing_for({"number": 7}) is True
    assert len(calls) == 2

    def only_destinations(*args: str):
        return [[{"filename": "tools/moved.sh", "status": "renamed"}]]

    monkeypatch.setattr(gm, "_gh_json", only_destinations)
    assert gm._plumbing_for({"number": 7}) is False, "destination alone is non-plumbing"
