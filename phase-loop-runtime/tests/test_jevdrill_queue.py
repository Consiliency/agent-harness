import copy
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from phase_loop_runtime.jevdrill_queue import ReportQueue


def report(event="event", task="task", workspace="workspace"):
    return {"envelope": {"project_id": "project", "workspace_id": workspace},
            "event": {"event_id": event, "task_id": task}}


def queue(tmp_path, **kwargs):
    return ReportQueue(tmp_path / "private" / "queue.sqlite", sanitize=copy.deepcopy, **kwargs)


@pytest.mark.parametrize("status", ["accepted", "duplicate"])
def test_only_matching_durable_acknowledgment_removes_report(tmp_path, status):
    now = [100.0]
    q = queue(tmp_path, clock=lambda: now[0])
    assert q.enqueue(report()) == "queued"
    for ack in [{"event_id": "other", "durable": True, "status": status},
                {"event_id": "event", "durable": False, "status": status}]:
        assert q.deliver_one(lambda _: ack) == "retry"
        assert q.status()["records"] == 1
        now[0] += 500
    restarted = queue(tmp_path, clock=lambda: now[0])
    assert restarted.deliver_one(lambda _: {"event_id": "event", "durable": True, "status": status}) == status
    assert restarted.status()["records"] == 0


def test_acknowledgment_loss_replays_exact_report(tmp_path):
    now = [100.0]
    seen = []
    q = queue(tmp_path, clock=lambda: now[0])
    q.enqueue(report())
    def lost(value):
        seen.append(value)
        raise TimeoutError()
    assert q.deliver_one(lost) == "retry"
    assert q.deliver_one(lost) == "empty"
    now[0] += 10
    assert queue(tmp_path, clock=lambda: now[0]).deliver_one(lost) == "retry"
    assert seen == [report(), report()]


def test_duplicates_conflicts_scope_and_corrections(tmp_path):
    q = queue(tmp_path)
    assert q.enqueue(report()) == "queued"
    assert q.enqueue(report()) == "duplicate"
    assert q.enqueue(report(task="changed")) == "conflict"
    assert q.enqueue(report(workspace="other")) == "queued"
    correction = report(event="correction")
    correction["event"]["supersedes_event_id"] = "event"
    assert q.enqueue(correction) == "queued"
    assert q.status() == {"records": 3, "dispositions": {"conflict": 1}}


@pytest.mark.parametrize("status", ["conflict", "rejected"])
def test_terminal_rejections_stay_visible_without_redelivery(tmp_path, status):
    q = queue(tmp_path)
    q.enqueue(report())
    assert q.deliver_one(lambda _: {"status": status, "event_id": "event", "durable": False}) == status
    assert q.deliver_one(lambda _: pytest.fail("terminal report sent")) == "empty"
    assert q.status() == {"records": 1, "dispositions": {status: 1}}


def test_overflow_and_expiry_have_persistent_loss_counters(tmp_path):
    now = [100.0]
    q = queue(tmp_path, clock=lambda: now[0])
    q.MAX_RECORDS = 1
    assert q.enqueue(report()) == "queued"
    assert q.enqueue(report(event="second")) == "overflow"
    now[0] += q.RETENTION_SECONDS
    assert q.status() == {"records": 0, "dispositions": {"overflow": 1, "expired": 1}}
    q.MAX_RECORD_BYTES = 1
    assert q.enqueue(report(event="large")) == "overflow"


def test_sanitization_happens_before_any_write(tmp_path):
    secret = "PRIVATE_SENTINEL_NEVER_PERSIST"
    value = report()
    value["raw_output"] = secret
    q = ReportQueue(tmp_path / "private" / "queue.sqlite", sanitize=lambda v: {k: v[k] for k in ("envelope", "event")})
    assert q.enqueue(value) == "queued"
    persisted = [p for p in q.path.parent.iterdir() if p.is_file()]
    assert persisted
    assert all(secret.encode() not in p.read_bytes() for p in persisted)
    assert q.deliver_one(lambda v: {"event_id": v["event"]["event_id"], "status": "accepted", "durable": True}) == "accepted"


def test_deletion_serializes_with_delivery_and_survives_restart(tmp_path):
    q = queue(tmp_path)
    other_producer = queue(tmp_path)
    q.enqueue(report())
    entered, finish = Event(), Event()
    def send(_):
        entered.set()
        assert finish.wait(3)
        raise TimeoutError()
    with ThreadPoolExecutor(max_workers=2) as pool:
        delivery = pool.submit(q.deliver_one, send)
        assert entered.wait(3)
        deletion = pool.submit(other_producer.delete_task, "project", "workspace", "task")
        finish.set()
        assert delivery.result() == "retry"
        deletion.result()
    restarted = queue(tmp_path)
    assert restarted.enqueue(report(event="another-producer")) == "deleted"
    assert restarted.deliver_one(lambda _: pytest.fail("deleted task delivered")) == "empty"
    assert restarted.enqueue(report(workspace="other")) == "queued"


@pytest.mark.parametrize("window", ["before_commit", "after_commit", "after_send"])
def test_process_crash_windows_recover_durable_reports(tmp_path, window):
    path = tmp_path / "private" / "queue.sqlite"
    script = '''
import copy, json, os, sys
from pathlib import Path
from contextlib import contextmanager
from phase_loop_runtime.jevdrill_queue import ReportQueue
path, window, payload = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
q = ReportQueue(path, sanitize=copy.deepcopy)
if window == 'before_commit':
    original = q._transaction
    @contextmanager
    def crash():
        with original() as db:
            yield db
            os._exit(23)
    q._transaction = crash
q.enqueue(payload)
if window == 'after_send':
    def send(value):
        path.with_suffix('.received').write_text(json.dumps(value))
        os._exit(23)
    q.deliver_one(send)
os._exit(23)
'''
    child = subprocess.run([sys.executable, "-c", script, str(path), window, json.dumps(report())], timeout=15)
    assert child.returncode == 23
    restarted = queue(tmp_path)
    assert restarted.status()["records"] == (0 if window == "before_commit" else 1)
    if window != "before_commit":
        seen = []
        def acknowledge(value):
            seen.append(value)
            return {"event_id": "event", "status": "duplicate" if window == "after_send" else "accepted", "durable": True}
        restarted.deliver_one(acknowledge)
        assert seen == [report()]
        if window == "after_send":
            assert json.loads(path.with_suffix('.received').read_text()) == seen[0]
        assert restarted.status()["records"] == 0


def test_corruption_stops_delivery_without_discarding_tombstones(tmp_path):
    from phase_loop_runtime.jevdrill_queue import QueueCorruption
    q = queue(tmp_path)
    q.delete_task("project", "workspace", "task")
    raw = b"synthetic corrupted database"
    q.path.write_bytes(raw)
    with pytest.raises(QueueCorruption, match="corrupt"):
        queue(tmp_path)
    assert q.path.read_bytes() == raw
    assert json.loads(q.corruption_marker.read_text()) == {"status": "corrupt", "automatic_action": "none"}
    with pytest.raises(QueueCorruption):
        q.enqueue(report())
    with pytest.raises(QueueCorruption):
        q.deliver_one(lambda _: pytest.fail("corrupt queue delivered"))


def test_objective_guard_reuses_anchored_transaction_and_bounds_admission(tmp_path, monkeypatch):
    import time
    from phase_loop_runtime import file_lock
    q = queue(tmp_path)
    with q.objective_guard():
        binding = getattr(q._objective_storage, "directory", None)
        if os.name == "nt":
            from phase_loop_runtime import windows_storage
            assert binding is not None and 0 < binding.deadline - time.monotonic() <= 5
            def forbidden(*_args, **_kwargs):
                pytest.fail("Nested transaction reopened its anchored directory")
            with monkeypatch.context() as local:
                local.setattr(windows_storage, "BoundDirectory", forbidden)
                assert q.enqueue(report()) == "queued"
                assert q.status()["records"] == 1
        else:
            assert q.enqueue(report()) == "queued"
    assert getattr(q._objective_storage, "directory", None) is None
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(time, "sleep", lambda elapsed: clock.__setitem__(0, clock[0] + elapsed))
    def held(*_args, **_kwargs):
        raise BlockingIOError()
    monkeypatch.setattr(file_lock, "acquire_exclusive", held)
    with pytest.raises(TimeoutError, match="lock deadline"):
        with q.objective_guard():
            pytest.fail("Busy objective guard admitted work")
    assert 5 <= clock[0] - 100 < 5.02


def test_objective_guard_bounds_other_thread_contention(tmp_path):
    import time
    q = queue(tmp_path)
    entered, finish = Event(), Event()
    def hold():
        with q.objective_guard():
            entered.set()
            assert finish.wait(10)
    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold)
        assert entered.wait(3)
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError, match="lock deadline"):
                with q.objective_guard():
                    pytest.fail("Contended thread guard admitted work")
            assert 4.9 <= time.monotonic() - started < 5.5
        finally:
            finish.set()
        holder.result()
