"""#45 — `phase-loop train-status`: non-mutating cross-repo train ledger inspection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phase_loop_runtime.cli import main as cli_main
from phase_loop_runtime.train_ledger import CoordinatorEvent, CoordinatorEventKind, LedgerRecord, append_record, default_ledger_path
from phase_loop_runtime.convergence.event_log import record_intent

from _runtime_tdd_guard import RuntimeCapabilityMissing
from runtime_content_tdd_adapter import run_mapped_case

TRAIN_MD = """# Release Train: t

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)

### Node: repo-b / specs/plan-b.md

**Depends on:** repo-a / specs/plan-a.md
**Channel:** submodule path=vendor/repo-a
"""


def _setup(tmp: Path) -> Path:
    train = tmp / "train.md"
    train.write_text(TRAIN_MD, encoding="utf-8")
    ledger = default_ledger_path(train.parent / ".train-ledger", train.stem)
    append_record(ledger, LedgerRecord(
        node_id="repo-a/specs/plan-a.md", status="merged", branch="b-a",
        pr_url="https://gh/a/1", upstream_merge_sha="sha-M-a", merge_order=0,
    ))
    append_record(ledger, LedgerRecord(
        node_id="repo-b/specs/plan-b.md", status="pr_open", branch="b-b",
        pr_url="https://gh/b/1", head_sha="sha-D-b", merge_order=1,
    ))
    return train


def test_train_status_human_output(tmp_path, capsys):
    train = _setup(tmp_path)
    rc = cli_main(["train-status", "--train", str(train)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[merged] repo-a/specs/plan-a.md" in out
    assert "[pr_open] repo-b/specs/plan-b.md" in out
    assert "sha-M-a" in out  # merged SHA surfaced


def test_train_status_json_output(tmp_path, capsys):
    train = _setup(tmp_path)
    rc = cli_main(["train-status", "--train", str(train), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    nodes = {n["node_id"]: n for n in payload["nodes"]}
    assert nodes["repo-a/specs/plan-a.md"]["status"] == "merged"
    assert nodes["repo-a/specs/plan-a.md"]["merged_sha"] == "sha-M-a"
    assert nodes["repo-b/specs/plan-b.md"]["status"] == "pr_open"
    # topo order: upstream before downstream
    assert [n["node_id"] for n in payload["nodes"]] == [
        "repo-a/specs/plan-a.md", "repo-b/specs/plan-b.md"
    ]


def test_train_status_no_ledger_lists_pending(tmp_path, capsys):
    train = tmp_path / "train.md"
    train.write_text(TRAIN_MD, encoding="utf-8")
    rc = cli_main(["train-status", "--train", str(train), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["nodes"] and all(n["status"] == "pending" for n in payload["nodes"])


def test_train_status_is_non_mutating(tmp_path):
    train = _setup(tmp_path)
    ledger = default_ledger_path(train.parent / ".train-ledger", train.stem)
    before = ledger.read_bytes()
    cli_main(["train-status", "--train", str(train)])
    assert ledger.read_bytes() == before, "train-status must not modify the ledger"


def test_train_status_missing_train_file(tmp_path, capsys):
    rc = cli_main(["train-status", "--train", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_train_status_event_log_without_train(tmp_path, capsys):
    log = tmp_path / "events.jsonl"
    record_intent(log, CoordinatorEvent(
        kind=CoordinatorEventKind.INTENT, train_id="t", node_id="n", roadmap_path="r",
        roadmap_digest="d", workspace_id=None, branch=None, base_ref=None, base_sha=None,
        head_sha=None, phase=None, action="execute", attempt_id="a", epoch=1,
    ))
    rc = cli_main(["train-status", "--event-log", str(log), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["train_id"] == "t"


# ---------------------------------------------------------------------------
# RUNTIME SL-3: event-log mode is read-only, restart-only, and fails closed


def test_train_status_event_log_round_trips_after_restart(tmp_path, capsys):
    """EC-RUNTIME-4 path-entered control: identical events render identically twice."""
    log = tmp_path / "events.jsonl"
    record_intent(log, CoordinatorEvent(
        kind=CoordinatorEventKind.INTENT, train_id="t", node_id="n", roadmap_path="r",
        roadmap_digest="d", workspace_id=None, branch=None, base_ref=None, base_sha=None,
        head_sha=None, phase=None, action="execute", attempt_id="a", epoch=1,
    ))
    before = log.read_bytes()
    assert cli_main(["train-status", "--event-log", str(log), "--json"]) == 0
    first = capsys.readouterr().out
    assert cli_main(["train-status", "--event-log", str(log), "--json"]) == 0
    assert capsys.readouterr().out == first
    assert log.read_bytes() == before, "event-log mode must never mutate the log"


def test_train_status_event_log_is_mutually_exclusive_with_train(tmp_path, capsys):
    log = tmp_path / "events.jsonl"
    record_intent(log, CoordinatorEvent(
        kind=CoordinatorEventKind.INTENT, train_id="t", node_id="n", roadmap_path="r",
        roadmap_digest="d", workspace_id=None, branch=None, base_ref=None, base_sha=None,
        head_sha=None, phase=None, action="execute", attempt_id="a", epoch=1,
    ))
    with pytest.raises(SystemExit):
        cli_main(["train-status", "--event-log", str(log), "--train", str(tmp_path / "train.md")])
    assert "mutually exclusive" in capsys.readouterr().err


def test_train_status_missing_event_log_fails_closed(tmp_path, capsys):
    """An absent event log is unknown state, never an empty successful train."""
    missing = tmp_path / "absent.jsonl"
    rc = cli_main(["train-status", "--event-log", str(missing), "--json"])
    captured = capsys.readouterr()

    def probe():
        if rc == 0:
            raise RuntimeCapabilityMissing("a missing event log is reported as an empty train")

    def assertion():
        assert rc != 0
        assert not missing.exists(), "event-log mode must stay read-only"
        assert captured.err.strip()

    run_mapped_case("cli.event-log-mode-fails-closed", probe=probe, assertion=assertion)
