"""Consiliency/agent-harness#1576 ask 1: the recovery record across runtime versions.

agent-harness#1550 (agent-harness#1310) added ``disposing_generation``,
``readmitting_generation`` and ``intervening_rotations`` to the write-once
``<transaction_id>.recovery.<generation>.json`` record.  ``record_recovery``
compares an existing record with the new payload for equality, so a record one
runtime version wrote, followed by a retry on another version in the SAME
generation, raised ``PublishTransactionConflict`` before any owner write or
provider call, and the key waited for an unrelated rotation or for the record
to be removed by hand.

The record is now the agent-harness#1296 shape whenever no rotation intervened
(the three fields appear only when one did), and a reader accepts an existing
record that carries the three fields with their no-rotation values.  The
mixed-version legs run the REAL older runtime in a subprocess, from a
``git archive`` of the pinned historical commit, the way the agent-harness#1551
board ran a pre-agent-harness#1313 tree.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from _fabpub_tdd_guard import FABPUB_SKIP_REASON, fabpub_capability_active
from test_fabpub_partition_rotation_789d import (
    ATTESTED_NOT_LANDED,
    _attestation,
    _publish_on_successor,
    _rotate,
)
from test_fabpub_recovery_chain_1310 import _disposed_then_superseded
from test_fabpub_sealed_head_recovery_1296 import _failed_sealed_publish, _owner
from test_fabpub_shared_epoch import _CountingAdapter

pytestmark = pytest.mark.skipif(not fabpub_capability_active(), reason=FABPUB_SKIP_REASON)

NEW_FIELDS = ("disposing_generation", "readmitting_generation", "intervening_rotations")
# Inputs, not outputs: historical runtimes whose record format is frozen.
# a1c3937e is main before agent-harness#1550 (the agent-harness#1296 record,
# the format v0.7.25 and v0.7.26 ship); 72ae134e is the agent-harness#1550 merge
# (the three fields always present, empty when no rotation intervened).
RUNTIME_1296 = "a1c3937e"
RUNTIME_1550 = "72ae134e"

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DRIVER = r"""
import json, sys
from pathlib import Path
from types import SimpleNamespace

args = json.loads(sys.argv[1])
from phase_loop_runtime import publishing
from test_fabpub_partition_rotation_789d import _release_router, _routed_service
from test_fabpub_shared_epoch import _publish_transaction_request

repo = Path(args["repo"])
transaction = publishing._load_transaction(
    repo, Path(args["checkpoint_root"]), args["transaction_id"], args["node_id"]
)
request = _publish_transaction_request(args["identity"], args["branch"], transaction, repo)


class CrashAfterRecord(Exception):
    pass


if args["mode"] == "crash_after_record":
    real = publishing.PublishTransaction.record_recovery

    def crash(self, record):
        real(self, record)
        raise CrashAfterRecord("crash after the recovery record, before the owner")

    publishing.PublishTransaction.record_recovery = crash

routed = _routed_service(SimpleNamespace(repo=repo))
out = {"runtime": publishing.__file__}
try:
    try:
        result = routed.service.execute(request)
        out.update(outcome=type(result).__name__, accepted=bool(result.accepted))
    except BaseException as error:
        out.update(outcome=type(error).__name__, message=str(error))
finally:
    _release_router(routed)
out["calls"] = len(routed.adapter.calls)
print("DRIVER " + json.dumps(out))
"""


def _historical_tree(tmp_path_factory, commit: str) -> Path:
    """Extract ``phase-loop-runtime/{src,tests}`` of ``commit`` once per session."""
    probe = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode:
        pytest.skip(f"historical runtime {commit} is not in this checkout (shallow clone or no git)")
    target = tmp_path_factory.getbasetemp() / f"runtime-{commit}"
    marker = target / ".extracted"
    if not marker.exists():
        archive = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "archive", commit, "phase-loop-runtime/src", "phase-loop-runtime/tests"],
            capture_output=True,
            check=True,
        ).stdout
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            tar.extractall(target, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        marker.write_text(commit, encoding="utf-8")
    return target / "phase-loop-runtime"


@pytest.fixture(scope="session")
def runtime_1296(tmp_path_factory) -> Path:
    return _historical_tree(tmp_path_factory, RUNTIME_1296)


@pytest.fixture(scope="session")
def runtime_1550(tmp_path_factory) -> Path:
    return _historical_tree(tmp_path_factory, RUNTIME_1550)


def _run_historical(tree: Path, p, mode: str) -> dict:
    """Drive one routed publish of ``p.request`` on the historical runtime at ``tree``."""
    transaction = p.transaction
    args = {
        "mode": mode,
        "repo": str(p.repo),
        "checkpoint_root": str(transaction.checkpoint_root),
        "transaction_id": transaction.transaction_id,
        "node_id": transaction.store.node_id,
        "identity": p.identity,
        "branch": p.request.branch,
    }
    env = dict(os.environ, PYTHONPATH=f"{tree / 'src'}{os.pathsep}{tree / 'tests'}")
    env.pop("PYTHONSAFEPATH", None)
    completed = subprocess.run(
        [sys.executable, "-c", _DRIVER, json.dumps(args)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tree),
        timeout=300,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("DRIVER ")]
    assert completed.returncode == 0 and lines, (
        f"historical driver failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}"
    )
    out = json.loads(lines[-1][len("DRIVER "):])
    assert Path(out["runtime"]).resolve().is_relative_to(tree.resolve()), out["runtime"]
    return out


def _records(p) -> dict[str, bytes]:
    root = p.transaction.store.root
    return {
        path.name: path.read_bytes()
        for path in sorted(root.glob(f"{p.transaction.transaction_id}.recovery.*.json"))
    }


def _crash_after_record_on_this_runtime(monkeypatch, outcome, p) -> None:
    from phase_loop_runtime import publishing

    real = publishing.PublishTransaction.record_recovery

    class CrashAfterRecord(Exception):
        pass

    def crash(self, record):
        real(self, record)
        raise CrashAfterRecord("crash after the recovery record, before the owner")

    monkeypatch.setattr(publishing.PublishTransaction, "record_recovery", crash)
    with pytest.raises(CrashAfterRecord):
        _publish_on_successor(None, outcome, p, p.request)
    monkeypatch.setattr(publishing.PublishTransaction, "record_recovery", real)
    assert _owner(outcome.store_root) is None, "the crash left an owner behind"


def _recovers_once_then_replays(outcome, p) -> None:
    adapter = _CountingAdapter()
    result, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(result, Exception), f"recovery refused: {result!r}"
    assert result.accepted is True and len(calls) == 1, (result, len(calls))
    replay, calls = _publish_on_successor(None, outcome, p, p.request, adapter=adapter)
    assert not isinstance(replay, Exception), f"replay refused: {replay!r}"
    assert replay.accepted is True and len(calls) == 1, "the replay reached the provider again"


def _disposed_in_place(tmp_path, monkeypatch):
    fx, p, key = _failed_sealed_publish(tmp_path, monkeypatch)
    first = _rotate(None, p, attestation=_attestation(p, dispositions={key: ATTESTED_NOT_LANDED}))
    assert first.generation == 1
    return p, key, first


def test_historical_runtime_is_the_archived_tree(runtime_1296, tmp_path, monkeypatch):
    """Guard: the subprocess imports the archived runtime, not this worktree's."""
    import phase_loop_runtime

    assert not Path(phase_loop_runtime.__file__).resolve().is_relative_to(runtime_1296.resolve())
    p, _key, _first = _disposed_in_place(tmp_path, monkeypatch)
    probe = subprocess.run(
        [sys.executable, "-c", "import phase_loop_runtime; print(phase_loop_runtime.__file__)"],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(runtime_1296 / "src")),
        cwd=str(runtime_1296),
        check=True,
    )
    assert Path(probe.stdout.strip()).resolve().is_relative_to(runtime_1296.resolve())


def test_no_rotation_record_is_the_1296_shape(tmp_path, monkeypatch):
    """With no intervening rotation the record carries none of the three fields."""
    p, key, first = _disposed_in_place(tmp_path, monkeypatch)
    _crash_after_record_on_this_runtime(monkeypatch, first, p)
    records = _records(p)
    assert list(records) == [f"{p.transaction.transaction_id}.recovery.1.json"]
    record = json.loads(records[f"{p.transaction.transaction_id}.recovery.1.json"])
    assert not set(NEW_FIELDS) & set(record), record
    assert (record["generation"], record["cutover_id"], record["effect_key"]) == (1, first.cutover_id, key)


def test_1296_record_then_this_runtime_retry_recovers_once(runtime_1296, tmp_path, monkeypatch):
    """Old record -> new retry: the 1296 runtime records and crashes before its owner;
    this runtime's retry in the same generation recovers exactly once."""
    p, _key, first = _disposed_in_place(tmp_path, monkeypatch)
    out = _run_historical(runtime_1296, p, "crash_after_record")
    assert (out["outcome"], out["calls"]) == ("CrashAfterRecord", 0), out
    assert _owner(first.store_root) is None
    written = _records(p)
    assert len(written) == 1 and not set(NEW_FIELDS) & set(json.loads(next(iter(written.values()))))
    _recovers_once_then_replays(first, p)
    assert _records(p) == written, "the retry rewrote the 1296 record"


def test_this_runtime_record_then_1296_retry_recovers_once(runtime_1296, tmp_path, monkeypatch):
    """New record -> old retry (the rolling-upgrade direction): this runtime records and
    crashes before its owner; the REAL 1296 runtime's retry in the same generation
    recovers exactly once, and a later retry here replays with no provider call."""
    p, _key, first = _disposed_in_place(tmp_path, monkeypatch)
    _crash_after_record_on_this_runtime(monkeypatch, first, p)
    written = _records(p)
    out = _run_historical(runtime_1296, p, "retry")
    assert (out["outcome"], out.get("accepted"), out["calls"]) == ("BrokerExecutionResult", True, 1), out
    assert _records(p) == written
    adapter = _CountingAdapter()
    replay, calls = _publish_on_successor(None, first, p, p.request, adapter=adapter)
    assert not isinstance(replay, Exception), f"replay refused: {replay!r}"
    assert replay.accepted is True and calls == [], "the replay reached the provider again"


def test_1550_record_then_this_runtime_retry_recovers_once(runtime_1550, tmp_path, monkeypatch):
    """A record the agent-harness#1550 runtime wrote (the three fields present, with
    their no-rotation values) is accepted by this runtime's retry, which recovers once."""
    p, _key, first = _disposed_in_place(tmp_path, monkeypatch)
    out = _run_historical(runtime_1550, p, "crash_after_record")
    assert (out["outcome"], out["calls"]) == ("CrashAfterRecord", 0), out
    written = _records(p)
    record = json.loads(next(iter(written.values())))
    assert (record["disposing_generation"], record["readmitting_generation"], record["intervening_rotations"]) == (1, 1, [])
    _recovers_once_then_replays(first, p)
    assert _records(p) == written, "the retry rewrote the 1550 record"


def test_intervening_rotation_record_carries_the_fields_and_recovers_once(
    runtime_1296, tmp_path, monkeypatch
):
    """With a rotation between the disposition and the retry the three fields are
    required.  The 1296 runtime cannot walk the chain: it refuses before any record or
    write, and this runtime then recovers exactly once."""
    p, key, first, second = _disposed_then_superseded(tmp_path, monkeypatch)
    out = _run_historical(runtime_1296, p, "retry")
    assert (out["outcome"], out["calls"]) == ("PublicationRecoveryRequired", 0), out
    assert _records(p) == {} and _owner(second.store_root) is None
    _crash_after_record_on_this_runtime(monkeypatch, second, p)
    written = _records(p)
    record = json.loads(written[f"{p.transaction.transaction_id}.recovery.2.json"])
    assert (record["disposing_generation"], record["readmitting_generation"]) == (1, 2)
    assert record["intervening_rotations"] == [second.cutover_id]
    _recovers_once_then_replays(second, p)
    assert _records(p) == written


def _admitted(p):
    from phase_loop_runtime import publishing

    return publishing._load_transaction(
        p.repo, p.transaction.checkpoint_root, p.transaction.transaction_id, p.transaction.store.node_id
    )


def test_a_genuinely_different_record_still_conflicts_and_names_its_path(tmp_path, monkeypatch):
    """Normalization drops the three fields only when they say "no rotation" and agree
    with ``generation``.  Anything else is still a conflict, typed, naming the record."""
    from phase_loop_runtime import publishing

    p, _key, first = _disposed_in_place(tmp_path, monkeypatch)
    _crash_after_record_on_this_runtime(monkeypatch, first, p)
    name = f"{p.transaction.transaction_id}.recovery.1.json"
    path = p.transaction.store.root / name
    base = json.loads(path.read_bytes())
    payload = {k: v for k, v in base.items() if k != "schema"}
    transaction = _admitted(p)
    variants = {
        "disposing_generation": {**base, "disposing_generation": 0, "readmitting_generation": 1, "intervening_rotations": []},
        "intervening_rotations": {**base, "disposing_generation": 1, "readmitting_generation": 1, "intervening_rotations": ["x"]},
        "readmitting_generation": {**base, "disposing_generation": 1, "readmitting_generation": 2, "intervening_rotations": []},
        "one_field_only": {**base, "intervening_rotations": []},
        "cutover_id": {**base, "cutover_id": "another-rotation"},
    }
    for label, existing in variants.items():
        path.write_text(json.dumps(existing, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        with pytest.raises(publishing.RecoveryRecordConflict) as caught:
            transaction.record_recovery(payload)
        assert caught.value.record_path == path, label
        assert str(path) in str(caught.value), label
        assert isinstance(caught.value, publishing.PublishTransactionConflict)
    # The no-rotation 1550 shape is the same authorization: accepted, left as found.
    same = {**base, "disposing_generation": 1, "readmitting_generation": 1, "intervening_rotations": []}
    body = json.dumps(same, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(body, encoding="utf-8")
    assert transaction.record_recovery(payload) == path
    assert path.read_text(encoding="utf-8") == body


def test_conflict_handoff_names_the_recovery_record(tmp_path, monkeypatch):
    """The human handoff for a recovery-record conflict names the record path."""
    from phase_loop_runtime import publishing
    from phase_loop_runtime.convergence.broker import live
    from test_publishing import _git, _human_publish_artifacts, _make_repo

    repo = _make_repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    plan, verification = _human_publish_artifacts(tmp_path)
    (repo / "owned.py").write_text("value = 1\n", encoding="utf-8")
    authority_root = tmp_path / "authority"
    inventory = live.probe_zero_history_bootstrap(
        cutover_id="human-record-conflict", authority_root=authority_root, worktrees=(repo,)
    )
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(authority_root))
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
    monkeypatch.setattr(publishing, "_check_gh_auth", lambda: None)
    record = tmp_path / "checkpoints" / "txn.recovery.3.json"

    def conflicting(*_args, **_kwargs):
        raise publishing.RecoveryRecordConflict(
            f"a different recovery is already recorded at {record}", record_path=record
        )

    monkeypatch.setattr(publishing, "publish_from_worktree", conflicting)
    result = publishing.publish_human_invoked_from_worktree(
        repo, ["owned.py"], plan_path=plan, verification_artifact_path=verification
    )
    assert result["reason"] == "publication_transaction_conflicted"
    handoff = result["handoff"]
    assert handoff["next_step"] == "resolve_publication_transaction_conflict"
    assert handoff["conflicting_recovery_record"] == str(record)
    assert "runbook" in handoff["recovery_procedure"]
