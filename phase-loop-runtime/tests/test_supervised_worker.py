"""Synthetic WORKER tests exercise landed admission and JOURNAL."""
from hashlib import sha256
import json
import os
from pathlib import Path
import threading

import pytest

from test_supervised_launch import case as _case, prepare, qualify
from phase_loop_runtime import run_status as rs, run_status_projection as projection
from phase_loop_runtime.convergence.adapters import patch_return as worker

case = _case
FIXTURE = Path(__file__).parent / "fixtures/supervised_worker_local/provider.py"


@pytest.fixture
def worker_case(case):
    case.executable.write_bytes(FIXTURE.read_bytes())
    case.executable.chmod(0o700)
    case.envelope["launch_inputs"]["wrappers"] = []
    case.envelope["assignment_digest"] = sha256(b"fixture-assignment").hexdigest()
    case.envelope["snapshot_reference"] = sha256(b"fixture-snapshot").hexdigest()
    case.settings.update(worker_audit_entry_cap=10000, worker_audit_byte_cap=10000000,
                         worker_proposal_cap=10000)
    case.config.config_path.write_text(json.dumps(case.settings))
    case.config.template_path.write_text('["{executable}", "patch"]')
    (case.root / "workspace/file").write_bytes(b"old\n")
    case.state = case.root / "state"
    return case


def run(case, mode="patch", **kwargs):
    case.config.template_path.write_text(json.dumps(["{executable}", mode]))
    prepared = prepare(case)
    assert hasattr(prepared, "view"), prepared
    result = worker.run_patch_return(prepared, config_bytes=case.config.config_path.read_bytes(),
                                    state_root=case.state, **kwargs)
    return result


@pytest.mark.parametrize("mode,status", [("patch", "returned"), ("malformed", "withheld_malformed"),
    ("oversized", "withheld_oversized"), ("fail", "withheld_incomplete"), ("empty", "absent"),
    ("write", "returned"), ("stderr", "returned")])
def test_proposal_table_and_binding(worker_case, mode, status):
    case = worker_case
    result = run(case, mode)
    assert result.state == "finished", result
    assert result.proposal.status == status
    assert result.worker_invocations == 1 and result.journal_complete and result.journal_anchor
    root = rs.open_journal_root(case.state / "journal", create=False)
    read = rs.read_attempt(root, case.envelope["attempt_id"])
    assert read.terminal.result_binding.evidence_envelope_digest == result.evidence_envelope_digest
    run_id = worker._run(result.identity)
    data = (case.state / "evidence" / run_id / "evidence.json").read_bytes()
    assert sha256(data).hexdigest() == result.evidence_envelope_digest
    assert b"synthetic instructions" not in data and b"fixture-stderr-sentinel" not in data
    if status == "returned":
        assert result.proposal.baselines[0].sha256 == sha256(b"old\n").hexdigest()
        assert worker.evidence_resolver(case.state)(read.identity,
            rs.Ref("proposal_bytes", result.proposal.proposal_bytes_digest, None)) == "present"


def test_reservation_replay_and_retry(worker_case):
    case = worker_case
    first = run(case)
    duplicate = run(case)
    assert first.state == "finished" and duplicate.state == "refused"
    assert duplicate.worker_invocations == 0
    case.envelope["attempt_id"] += "-retry"
    second = run(case)
    assert second.state == "finished" and worker._run(first.identity) != worker._run(second.identity)


def test_prestart_cancel_and_unknown_cancel(worker_case):
    case = worker_case
    event = threading.Event()
    event.set()
    result = run(case, cancel=event)
    assert result.refusal == "cancelled_before_start" and result.worker_invocations == 0
    assert not (case.state / "evidence").exists()
    assert worker.cancel_attempt(state_root=case.state, attempt_id=case.envelope["attempt_id"]) == "already_terminal"
    assert worker.cancel_attempt(state_root=case.state, attempt_id="absent") == "unknown_attempt"


@pytest.mark.parametrize("field,value,reason", [("worker_proposal_cap", 0, "worker_settings_invalid"),
    ("worker_audit_entry_cap", True, "worker_settings_invalid")])
def test_settings_refuse_before_reservation(worker_case, field, value, reason):
    case = worker_case
    case.settings[field] = value
    case.config.config_path.write_text(json.dumps(case.settings))
    assert run(case).refusal == reason
    assert not case.state.exists()


def test_config_changed_before_reservation(worker_case):
    case = worker_case
    result = worker.run_patch_return(prepare(case), config_bytes=b"{}", state_root=case.state)
    assert result.refusal == "config_changed" and not case.state.exists()


def test_jcs_context_and_provider_basename(worker_case):
    from phase_loop_runtime.convergence.adapters.codex import run_codex_patch_return
    import rfc8785
    case = worker_case
    context = {"__proto__": {"fixture": 2}, "value": 1}
    case.envelope["caller_context"] = context
    prepared = prepare(case)
    refusal = run_codex_patch_return(prepared, config_bytes=case.config.config_path.read_bytes(), state_root=case.state)
    assert refusal.refusal == "provider_mismatch" and not case.state.exists()
    result = worker.run_patch_return(prepared, config_bytes=case.config.config_path.read_bytes(), state_root=case.state)
    assert result.identity.caller_context_sha256 == sha256(rfc8785.dumps(context)).hexdigest()


def test_default_roots_agree():
    assert worker.default_state_root() / "journal" == rs.default_journal_root()


@pytest.mark.parametrize("phase", ["queued", "running", "terminal", "event"])
@pytest.mark.parametrize("operation", ["write", "fsync"])
def test_real_writer_fault_stops_journal_calls(worker_case, monkeypatch, phase, operation, prestart=False, exception=OSError):
    case = worker_case
    original_open = rs.open_writer
    original_io = getattr(os, operation)
    calls, failed, after_failure = [], [], []
    def opened(*args, **kwargs):
        real = original_open(*args, **kwargs)
        class Delegating:
            def __getattr__(self, name):
                method = getattr(real, name)
                if name == "close":
                    return method
                def invoke(*a, **kw):
                    if failed:
                        after_failure.append(name)
                    assert not failed, "WORKER called writer after failure"
                    calls.append((name, a))
                    selected = (a and a[0] == phase) or name == phase
                    if not selected:
                        return method(*a, **kw)
                    def fault(fd, *rest):
                        path = os.readlink(f"/proc/self/fd/{fd}")
                        if "segments" in path or path.endswith(".jsonl"):
                            if operation == "fsync":
                                original_io(fd, *rest)
                            failed.append(True)
                            raise exception("synthetic journal I/O")
                        return original_io(fd, *rest)
                    with pytest.MonkeyPatch.context() as patch:
                        patch.setattr(os, operation, fault)
                        return method(*a, **kw)
                return invoke
        return Delegating()
    monkeypatch.setattr(rs, "open_writer", opened)
    event = threading.Event()
    if prestart:
        event.set()
    result = run(case, cancel=event)
    assert failed, calls
    assert not after_failure
    assert not result.journal_complete and result.journal_anchor is None
    assert result.worker_invocations == (0 if phase in ("queued", "running") or prestart else 1)
    if not result.worker_invocations:
        assert result.refusal == "journal_unavailable" and not (case.state / "evidence").exists()
    if operation == "fsync":
        root = rs.open_journal_root(case.state / "journal", create=False)
        live = projection.attempt_status(root, case.envelope["attempt_id"])
        stale = projection.attempt_status(root, case.envelope["attempt_id"], observer=lambda _: (False, None))
        if phase == "running":
            assert live.display == "running" and stale.display == "stale_unknown"
        elif phase == "terminal":
            assert live.state == stale.state == ("refused" if prestart else "finished")
            if prestart:
                assert live.refusal.reason == "cancelled_before_start" and result.refusal == "journal_unavailable"


@pytest.mark.parametrize("operation", ["active", "proposal", "evidence", "sealed", "ledger"])
def test_evidence_operation_failure_null_binding(worker_case, monkeypatch, operation):
    case = worker_case
    original_write, original_mark = worker._write, worker.retention.mark
    def write(path, data):
        selected = ((operation == "proposal" and path.name == "proposal.bin") or
                    (operation == "evidence" and path.name == "evidence.json") or
                    (operation == "ledger" and path.parent.name == "evidence-ledger"))
        if selected:
            raise OSError("synthetic evidence operation")
        return original_write(path, data)
    def mark(root, run, state, **kwargs):
        if operation == state:
            raise OSError("synthetic retention operation")
        return original_mark(root, run, state, **kwargs)
    monkeypatch.setattr(worker, "_write", write)
    monkeypatch.setattr(worker.retention, "mark", mark)
    result = run(case)
    assert result.proposal.status == "withheld_evidence_error"
    assert result.proposal.proposal_bytes_digest is None and result.proposal.locator is None
    assert result.evidence_envelope_digest is None
    root = rs.open_journal_root(case.state / "journal", create=False)
    read = rs.read_attempt(root, case.envelope["attempt_id"])
    assert read.terminal.result_binding is None
    assert not any(json.loads(line)["body"]["refs"] for line in read.lines
                   if json.loads(line)["line_kind"] == "event")
    assert read.terminal.termination.reason == "completed"
    assert not (case.state / "evidence" / worker._run(result.identity) / "proposal.bin").exists()


@pytest.mark.parametrize("tier", ["post_write_audit_only", "provider_readonly_patch_return_audit"])
@pytest.mark.parametrize("scope", ["workspace", "target", "refs", "objects"])
def test_audit_scopes(worker_case, monkeypatch, tier, scope):
    case = worker_case
    if tier == "provider_readonly_patch_return_audit":
        qualification = qualify(case)
        record = json.loads(qualification.read_bytes())
        record["wrappers"] = []
        qualification.write_text(json.dumps(record))
    if scope in ("refs", "objects"):
        (case.root / "target/.git" / scope).mkdir(parents=True)
    original = worker.run_bounded_capture
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        path = case.root / ("workspace/new" if scope == "workspace" else
                           "target/new" if scope == "target" else f"target/.git/{scope}/new")
        path.write_text("synthetic change")
        return result
    monkeypatch.setattr(worker, "run_bounded_capture", changed)
    result = run(case)
    changed_scope = scope in ("target", "refs") or (scope == "workspace" and tier.startswith("provider_"))
    assert result.proposal.status == ("withheld_unexplained_change" if changed_scope else "returned")


@pytest.mark.parametrize("kind", ["fifo", "gitfile", "gitlink", "entries", "bytes"])
def test_before_audit_refusal(worker_case, kind):
    case = worker_case
    if kind == "fifo":
        os.mkfifo(case.root / "workspace/fifo")
    elif kind == "gitfile":
        (case.root / "target/.git").write_text("gitdir: /elsewhere")
    elif kind == "gitlink":
        (case.root / "target/.git").symlink_to(case.root / "references", target_is_directory=True)
    else:
        (case.root / "workspace/second").write_text("fixture")
        case.settings["worker_audit_entry_cap" if kind == "entries" else "worker_audit_byte_cap"] = 1
        case.config.config_path.write_text(json.dumps(case.settings))
    result = run(case)
    assert result.refusal == "audit_error" and not (case.state / "evidence").exists()


def test_retention_identity_and_unrecorded_deletion(worker_case, monkeypatch):
    case = worker_case
    first = run(case)
    jid = rs.AttemptIdentity(first.identity.assignment_digest, first.identity.envelope_digest,
                            first.identity.run_id, first.identity.attempt_id)
    ref = rs.Ref("proposal_bytes", first.proposal.proposal_bytes_digest, None)
    resolver = worker.evidence_resolver(case.state)
    assert resolver(jid, ref) == "present"
    root = case.state / "evidence"
    registry = root / worker.retention.REGISTRY / (worker._run(jid) + ".json")
    completed = json.loads(registry.read_bytes())["completed_at"]
    original = worker.retention.prune
    monkeypatch.setattr(worker.retention, "prune", lambda root, **kw:
        original(root, **kw, now=completed + 100 * 86400))
    case.envelope["attempt_id"] += "-retry"
    run(case)
    assert resolver(jid, ref) == "retention_dropped"
    rootj = rs.open_journal_root(case.state / "journal", create=False)
    assert rs.read_attempt(rootj, jid.attempt_id).terminal is not None
    page = projection.read_page(rootj, json.dumps(dict(assignment_digest=jid.assignment_digest,
        page_size=100, cursor=None)).encode(), evidence=resolver)
    assert isinstance(page, projection.PageResult) and page.page["omitted"]["retention_dropped"] >= 2
    assert first.proposal.proposal_bytes_digest.encode() in b"".join(rs.read_attempt(rootj, jid.attempt_id).lines)
    other = run(case)  # replay does not create any evidence
    assert other.worker_invocations == 0
    (case.state / "evidence-ledger" / (worker._run(jid) + ".retired")).unlink()
    assert resolver(jid, ref) == "unknown"


def _start_launcher(case, *, mode="running", result="result.json"):
    import subprocess
    import sys
    launcher = FIXTURE.with_name("launcher.py")
    job = case.root / (result + ".job")
    job.write_text(json.dumps(dict(root=str(case.root), config=str(case.config.config_path),
        template=str(case.config.template_path), envelope=case.envelope, mode=mode, result=result)))
    command = [sys.executable, "-I", str(launcher), str(Path(worker.__file__).parents[3]), str(job)]
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE), (("-I", str(launcher)),)


def _finish_launcher(process):
    try:
        out, err = process.communicate(timeout=15)
        assert process.returncode == 0, (out, err)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def _await_state(case, state):
    import time
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        root = rs.open_journal_root(case.state / "journal", create=False)
        if not isinstance(root, rs.JournalRefused):
            observed = projection.attempt_status(root, case.envelope["attempt_id"])
            if observed.state == state:
                return root
        time.sleep(.02)
    raise AssertionError("fixture launcher did not reach " + state)


@pytest.mark.parametrize("stage", ["queued", "running", "terminal"])
def test_native_cancel_fixture_lifecycle(worker_case, stage):
    case = worker_case
    if stage != "terminal":
        case.config.template_path.write_text('["{executable}", "wait"]')
    process, commands = _start_launcher(case, mode=stage)
    try:
        _await_state(case, "finished" if stage == "terminal" else stage)
        if stage == "queued":
            import time
            deadline = time.monotonic() + 5
            while not (case.root / "ready").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert (case.root / "ready").exists()
        outcome = worker.cancel_attempt(state_root=case.state, attempt_id=case.envelope["attempt_id"],
                                        launcher_commands=commands)
        assert outcome == ("already_terminal" if stage == "terminal" else "cancelled")
        assert worker.cancel_attempt(state_root=case.state, run_id=case.envelope["run_id"],
                                     launcher_commands=commands) == "already_terminal"
        _finish_launcher(process)
        record = json.loads((case.root / "result.json").read_bytes())
        if stage != "terminal":
            assert record["proposal"] is None or record["proposal"]["proposal_bytes_digest"] is None
    finally:
        if process.poll() is None:
            process.terminate()
            _finish_launcher(process)


def test_replay_four_processes_and_crash_reservation(worker_case):
    case = worker_case
    processes = [_start_launcher(case, result=f"result-{i}.json")[0] for i in range(4)]
    try:
        for process in processes:
            _finish_launcher(process)
        results = [json.loads((case.root / f"result-{i}.json").read_bytes()) for i in range(4)]
        assert sum(row["worker_invocations"] for row in results) == 1
        assert sum(row["state"] == "finished" for row in results) == 1
        case.envelope["attempt_id"] += "-crash"
        process, _ = _start_launcher(case, mode="crash", result="crashed.json")
        _finish_launcher(process)
        assert not (case.root / "crashed.json").exists()
        process, _ = _start_launcher(case, result="replay.json")
        _finish_launcher(process)
        assert json.loads((case.root / "replay.json").read_bytes())["worker_invocations"] == 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_cancel_unverified_and_stale_owner(worker_case, monkeypatch):
    case = worker_case
    case.config.template_path.write_text('["{executable}", "wait"]')
    process, commands = _start_launcher(case)
    try:
        _await_state(case, "running")
        signals = []
        monkeypatch.setattr(worker.signal, "pidfd_send_signal", lambda *args: signals.append(args))
        record = case.state / "launchers" / (case.envelope["attempt_id"] + ".json")
        body = json.loads(record.read_bytes())
        body["pid"] = os.getpid()
        record.write_text(json.dumps(body))
        assert worker.cancel_attempt(state_root=case.state, attempt_id=case.envelope["attempt_id"],
                                     launcher_commands=commands) == "owner_unverified"
        assert signals == [] and process.poll() is None
    finally:
        process.terminate()
        _finish_launcher(process)
    # A nonterminal left behind by a crash has no live verified writer.
    case.envelope["attempt_id"] += "-stale"
    process, _ = _start_launcher(case, mode="crash", result="crash.json")
    _finish_launcher(process)
    assert worker.cancel_attempt(state_root=case.state, attempt_id=case.envelope["attempt_id"]) == "owner_not_live"


@pytest.mark.parametrize("field", ["workspace", "device", "inode", "executable", "wrapper"])
def test_each_prespawn_recheck(worker_case, monkeypatch, field):
    case = worker_case
    if field == "wrapper":
        case.wrapper.write_bytes(b"#!/bin/sh\nexec \"$@\"\n")
        case.envelope["launch_inputs"]["wrappers"] = [str(case.wrapper)]
    original = worker.run_bounded_capture
    def changed(request, *, before_spawn, cancel):
        if field in ("workspace", "device", "inode"):
            kind, device, inode = worker.classify_workspace(Path(case.envelope["launch_inputs"]["workspace"]),
                Path(case.envelope["launch_inputs"]["target"]), case.envelope["launch_inputs"]["tier"])
            observed = {"workspace": ("other", device, inode), "device": (kind, device + 1, inode),
                        "inode": (kind, device, inode + 1)}[field]
            monkeypatch.setattr(worker, "classify_workspace", lambda *args: observed)
        else:
            path = case.executable if field == "executable" else case.wrapper
            path.write_bytes(path.read_bytes() + b"\n# changed\n")
        return original(request, before_spawn=before_spawn, cancel=cancel)
    monkeypatch.setattr(worker, "run_bounded_capture", changed)
    result = run(case)
    assert result.refusal == field + "_changed" and result.worker_invocations == 0


def test_worker_setsid_limit_and_reap(worker_case):
    import ctypes
    import signal
    case = worker_case
    library = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert library.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert library.prctl(36, 1, 0, 0, 0) == 0
    case.envelope["launch_inputs"]["timeout"] = 1
    pid = None
    try:
        result = run(case, "escape")
        pid = int((case.root / "workspace/escape.pid").read_text())
        assert result.termination.reason == "completed"
        assert result.proposal.status == "withheld_incomplete"
        os.kill(pid, 0)
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        assert library.prctl(36, previous.value, 0, 0, 0) == 0


def test_consumed_admission_has_no_effects(worker_case):
    from phase_loop_runtime import supervised_launch
    case = worker_case
    prepared = prepare(case)
    assert not isinstance(supervised_launch.consume_admission(prepared), supervised_launch.Refused)
    result = worker.run_patch_return(prepared, config_bytes=case.config.config_path.read_bytes(), state_root=case.state)
    assert result.refusal == "token_spent" and not case.state.exists()


def test_reservation_failure_has_no_followup(worker_case, monkeypatch):
    case = worker_case
    called = []
    monkeypatch.setattr(rs, "reserve_attempt", lambda *a, **k: rs.JournalRefused("synthetic_reservation_refusal"))
    original = rs.open_writer
    def opened(*args, **kwargs):
        called.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(rs, "open_writer", opened)
    result = run(case)
    assert result.refusal == "synthetic_reservation_refusal" and not called


def test_reservation_and_running_precede_spawn(worker_case, monkeypatch):
    order = []
    original_reserve, original_capture = rs.reserve_attempt, worker.run_bounded_capture
    def reserve(*args, **kwargs):
        result = original_reserve(*args, **kwargs)
        order.append("reserved")
        return result
    def capture(request, *, before_spawn, cancel):
        def before():
            refusal = before_spawn()
            root = rs.open_journal_root(worker_case.state / "journal", create=False)
            observed = rs.read_attempt(root, worker_case.envelope["attempt_id"])
            order.append(observed.state)
            return refusal
        return original_capture(request, before_spawn=before, cancel=cancel)
    monkeypatch.setattr(rs, "reserve_attempt", reserve)
    monkeypatch.setattr(worker, "run_bounded_capture", capture)
    result = run(worker_case)
    assert result.state == "finished" and order == ["reserved", "running"]


def test_evidence_events_and_bindings(worker_case):
    case = worker_case
    result = run(case, "stderr")
    assert result.state == "finished" and result.journal_complete
    root = rs.open_journal_root(case.state / "journal", create=False)
    read = rs.read_attempt(root, case.envelope["attempt_id"])
    lines = [json.loads(line) for line in read.lines]
    events = [line["body"] for line in lines if line["line_kind"] == "event"]
    assert [event["message"]["text"] for event in events] == ["attempt evidence bound", "proposal bytes captured"]
    assert all(ref["locator"] is None for event in events for ref in event["refs"])
    path = case.state / "evidence" / worker._run(result.identity) / "evidence.json"
    record = json.loads(path.read_bytes())
    assert record["identity"] == json.loads(json.dumps(worker.asdict(result.identity)))
    assert record["instruction_digest"] == sha256(b"synthetic instructions").hexdigest()
    assert record["config_digest"] == sha256(case.config.config_path.read_bytes()).hexdigest()
    assert record["template_digest"] == sha256(case.config.template_path.read_bytes()).hexdigest()
    assert record["executable"]["sha256"] == sha256(case.executable.read_bytes()).hexdigest()
    assert record["argv"] == [str(case.executable), "stderr"]
    assert record["streams_complete"] and record["stdin_delivered"]
    assert record["workspace_kind"] == "separate" and record["tier"] == "post_write_audit_only"
    assert record["device"] == (case.root / "workspace").stat().st_dev
    assert record["inode"] == (case.root / "workspace").stat().st_ino
    assert record["environment_names"] == sorted(worker.worker_child_environment(frozenset()))
    assert record["exec_binding"] == "path_recheck"
    assert record["worker_invocations"] == 1 and record["duration_ns"] > 0
    assert record["proposal"]["proposal_bytes_digest"] == result.proposal.proposal_bytes_digest
    serialized = json.dumps(worker.asdict(result)).encode()
    for sentinel in (b"synthetic instructions", b"fixture-stderr-sentinel", b"-old", b"+new"):
        assert sentinel not in serialized and sentinel not in b"".join(read.lines) and sentinel not in path.read_bytes()


def test_retention_ordering(worker_case, monkeypatch):
    actions = []
    original_mark, original_write = worker.retention.mark, worker._write
    def mark(root, run_id, state, **kwargs):
        actions.append(state)
        return original_mark(root, run_id, state, **kwargs)
    def write(path, data):
        if path.name in ("proposal.bin", "evidence.json") or path.parent.name == "evidence-ledger":
            actions.append(path.name if path.parent.name != "evidence-ledger" else "ledger")
        return original_write(path, data)
    monkeypatch.setattr(worker.retention, "mark", mark)
    monkeypatch.setattr(worker, "_write", write)
    assert run(worker_case).state == "finished"
    assert actions == ["active", "proposal.bin", "evidence.json", "sealed", "ledger"]


def test_after_audit_error_and_incomplete(worker_case, monkeypatch, incomplete=False):
    if incomplete:
        from dataclasses import replace
        original = worker.run_bounded_capture
        monkeypatch.setattr(worker, "run_bounded_capture", lambda *a, **k: replace(original(*a, **k), streams_complete=False))
    else:
        original = worker._audit
        calls = []
        def audit(*args):
            calls.append(1)
            if len(calls) == 2:
                raise ValueError("synthetic after-audit failure")
            return original(*args)
        monkeypatch.setattr(worker, "_audit", audit)
    result = run(worker_case)
    assert result.proposal.status == ("withheld_incomplete" if incomplete else "withheld_audit_error")


WORKER_CONTROLS = {
    "consume-before-reserve": ('inputs = consume_admission(prepared)', 'inputs = prepared.view.inputs', "consumed"),
    "reservation-failure": ('if isinstance(reservation, journal.JournalRefused):', 'if False and isinstance(reservation, journal.JournalRefused):', "reservation"),
    "reservation-before-spawn": ('reservation = journal.reserve_attempt(root, jid,', 'run_bounded_capture(CaptureRequest(identity.attempt_id, inputs.argv, Path(inputs.workspace), inputs.timeout, inputs.instruction, settings.proposal_cap, worker_child_environment(settings.environment_allow)), before_spawn=lambda: None, cancel=threading.Event())\n        reservation = journal.reserve_attempt(root, jid,', "order"),
    "running-before-spawn": ('writer.call("state", "running", worker_invocations=1)', 'None', "order"),
    "rule-w-stop": ('if self.failed:\n            return None', 'if False and self.failed:\n            return None', "writer"),
    "evidence-event": ('writer.call("event", "attempt evidence bound", refs=', 'writer.call("event", "proposal withheld", refs=', "bindings"),
    "proposal-event": ('writer.call("event", "proposal bytes captured", refs=', 'writer.call("event", "proposal withheld", refs=', "bindings"),
    "cancel-before-start": ('if cancel.is_set():\n                return SpawnRefused("cancelled_before_start")', 'if False and cancel.is_set():\n                return SpawnRefused("cancelled_before_start")', "cancel"),
    "decision-incomplete": ('if termination.reason != "completed" or captured.exit_code != 0 or not captured.streams_complete:', 'if False:', "incomplete"),
    "decision-oversized": ('elif captured.proposal_overflow:', 'elif False:', "oversized"),
    "decision-audit-error": ('elif audit_error:', 'elif False:', "audit-error"),
    "decision-unexplained": ('elif unexplained:', 'elif False:', "target"),
    "decision-absent": ('elif not data:', 'elif False:', "absent"),
    "decision-malformed": ('paths = _paths(data)', 'paths = []', "malformed"),
    "decision-returned": ('status = "returned"', 'status = "withheld_malformed"', "returned"),
    "evidence-error": ('ProposalReturn("withheld_evidence_error",', 'ProposalReturn("absent",', "evidence-error"),
    "baseline": ('baselines.get(path, BaselineIdentity(path, None, None))', 'BaselineIdentity(path, None, None)', "returned"),
    "audit-workspace": ('if key[0] == "target" or inputs.tier == "provider_readonly_patch_return_audit":', 'if key[0] == "target":', "workspace"),
    "audit-target": ('if key[0] == "target" or inputs.tier == "provider_readonly_patch_return_audit":', 'if inputs.tier == "provider_readonly_patch_return_audit":', "target"),
    "audit-refs": ('if path == ".git/objects" or path.startswith(".git/objects/"):', 'if path.startswith(".git/refs") or path == ".git/objects" or path.startswith(".git/objects/"):', "refs"),
    "evidence-binding": ('config_digest=inputs.config_digest, template_digest=', 'config_digest="stale", template_digest=', "bindings"),
    "active-before-write": ('retention.mark(evidence_root, run, "active", owner_pid=os.getpid())', 'None', "retention-order"),
    "seal-after-write": ('retention.mark(evidence_root, run, "sealed")', 'None', "retention-order"),
    "ledger-retirement": ('_write(state_root / "evidence-ledger" / (retired + ".retired"), b"")', 'None', "retention"),
    "resolver-unknown": ('        return "unknown"\n    return resolve', '        return "present"\n    return resolve', "retention"),
    "jcs-digest": ('context_digest = sha256(rfc8785.dumps(_plain(prepared.view.envelope["caller_context"]))).hexdigest()', 'context_digest = "0" * 64', "jcs"),
}
for _field in ("workspace", "device", "inode"):
    WORKER_CONTROLS["recheck-" + _field] = ('if actual != expected:', f'if actual != expected and reason != "{_field}_changed":', _field + "-recheck")
for _field in ("executable", "wrapper"):
    WORKER_CONTROLS["recheck-" + _field] = ('if _executable_digest(Path(executable.path)) != executable.digest:',
        f'if reason != "{_field}_changed" and _executable_digest(Path(executable.path)) != executable.digest:', _field + "-recheck")


def _worker_source_copy(monkeypatch, control):
    import sys
    import types
    source = Path(worker.__file__).read_text()
    old, new, _ = WORKER_CONTROLS[control]
    assert old in source, control
    module = types.ModuleType("phase_loop_runtime.convergence.adapters._worker_copy")
    module.__package__, module.__file__ = worker.__package__, worker.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source.replace(old, new, 1), module.__file__, "exec"), module.__dict__)
    return module


def _worker_control_witness(case, monkeypatch, witness):
    if witness == "consumed":
        test_consumed_admission_has_no_effects(case)
    elif witness == "reservation":
        test_reservation_failure_has_no_followup(case, monkeypatch)
    elif witness == "order":
        test_reservation_and_running_precede_spawn(case, monkeypatch)
    elif witness == "writer":
        test_real_writer_fault_stops_journal_calls(case, monkeypatch, "event", "fsync")
    elif witness == "bindings":
        test_evidence_events_and_bindings(case)
    elif witness == "cancel":
        test_prestart_cancel_and_unknown_cancel(case)
    elif witness == "incomplete":
        test_after_audit_error_and_incomplete(case, monkeypatch, incomplete=True)
    elif witness == "audit-error":
        test_after_audit_error_and_incomplete(case, monkeypatch)
    elif witness in ("target", "refs", "workspace"):
        test_audit_scopes(case, monkeypatch,
            "provider_readonly_patch_return_audit" if witness == "workspace" else "post_write_audit_only", witness)
    elif witness in ("returned", "absent", "malformed", "oversized"):
        mode = {"returned": "patch", "absent": "empty"}.get(witness, witness)
        status = witness if witness in ("returned", "absent") else "withheld_" + witness
        test_proposal_table_and_binding(case, mode, status)
    elif witness == "evidence-error":
        test_evidence_operation_failure_null_binding(case, monkeypatch, "evidence")
    elif witness == "retention-order":
        test_retention_ordering(case, monkeypatch)
    elif witness == "retention":
        test_retention_identity_and_unrecorded_deletion(case, monkeypatch)
    elif witness == "jcs":
        test_jcs_context_and_provider_basename(case)
    elif witness.endswith("-recheck"):
        test_each_prespawn_recheck(case, monkeypatch, witness.removesuffix("-recheck"))
    else:
        raise AssertionError("unrecognized control")


@pytest.mark.parametrize("control", sorted(WORKER_CONTROLS))
@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_worker_source_controls(worker_case, monkeypatch, control, mutated):
    import sys
    if mutated:
        copy = _worker_source_copy(monkeypatch, control)
        monkeypatch.setattr(sys.modules[__name__], "worker", copy)
        with pytest.raises(AssertionError):
            _worker_control_witness(worker_case, monkeypatch, WORKER_CONTROLS[control][2])
    else:
        _worker_control_witness(worker_case, monkeypatch, WORKER_CONTROLS[control][2])


CANCEL_CONTROLS = {
    "record-mode": ('or stat.S_IMODE(info.st_mode) != 0o600', ''),
    "record-owner": ('or info.st_uid != os.geteuid()', ''),
    "record-regular": ('not stat.S_ISREG(info.st_mode) or ', ''),
    "record-nofollow": ('fd = os.open(attempt_id + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)', 'fd = os.open(attempt_id + ".json", os.O_RDONLY | os.O_NONBLOCK, dir_fd=parent)'),
    "writer-identity": ('!= (pid, record["process_start_time"], record["nonce"])', '== (pid, record["process_start_time"], record["nonce"])'),
    "pidfd-open": ('pidfd = os.pidfd_open(pid)', 'pidfd = os.open("/dev/null", os.O_RDONLY)'),
    "start-identity": ('if journal.process_start_identity(pid) != record["process_start_time"]:', 'if False:'),
    "exe-record": ('if exe != record["exe_realpath"] or exe != str(Path("/proc/self/exe").resolve()):', 'if exe != str(Path("/proc/self/exe").resolve()):'),
    "exe-interpreter": ('if exe != record["exe_realpath"] or exe != str(Path("/proc/self/exe").resolve()):', 'if exe != record["exe_realpath"]:'),
    "cmdline-digest": ('if sha256(cmdline).hexdigest() != record["cmdline_sha256"]:', 'if False:'),
    "command-policy": ('if not any(args[1:1 + len(command)] == command for command in launcher_commands):', 'if False:'),
    "record-lock": ('if lock_type == fcntl.F_UNLCK or owner != pid:', 'if False:'),
    "pidfd-target": ('signal.pidfd_send_signal(pidfd, signal.SIGTERM)', 'signal.pidfd_send_signal(pid, signal.SIGTERM)'),
}


def _cancel_source_copy(monkeypatch, control):
    import sys
    import types
    source = Path(worker.__file__).read_text()
    # Scope record guards to cancel, never alter an earlier matching file guard.
    prefix, tail = source.split("def cancel_attempt(", 1)
    old, new = CANCEL_CONTROLS[control]
    assert old in tail
    module = types.ModuleType("phase_loop_runtime.convergence.adapters._cancel_copy")
    module.__file__, module.__package__ = worker.__file__, worker.__package__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(prefix + "def cancel_attempt(" + tail.replace(old, new, 1), module.__file__, "exec"), module.__dict__)
    return module


def _cancel_control_witness(case, monkeypatch, module, control):
    import fcntl
    import struct
    import stat
    from types import SimpleNamespace
    case.config.template_path.write_text('["{executable}", "wait"]')
    process, commands = _start_launcher(case)
    try:
        _await_state(case, "running")
        path = case.state / "launchers" / (case.envelope["attempt_id"] + ".json")
        record = json.loads(path.read_bytes())
        sent = []
        def signal_spy(target, sig):
            try:
                kind = os.readlink(f"/proc/self/fd/{target}")
            except OSError:
                kind = "not-a-descriptor"
            sent.append((target, kind, sig))
        monkeypatch.setattr(module.signal, "pidfd_send_signal", signal_spy)
        if control == "record-mode":
            path.chmod(0o644)
        elif control in ("record-owner", "record-regular"):
            original = os.fstat
            def fstat(fd):
                result = original(fd)
                if os.readlink(f"/proc/self/fd/{fd}") == str(path):
                    return SimpleNamespace(st_uid=-1 if control == "record-owner" else result.st_uid,
                        st_mode=stat.S_IFIFO | 0o600 if control == "record-regular" else result.st_mode,
                        st_size=result.st_size)
                return result
            monkeypatch.setattr(os, "fstat", fstat)
        elif control == "record-nofollow":
            held = path.with_name("held.json")
            path.rename(held)
            path.symlink_to(held)
        elif control == "writer-identity":
            record["nonce"] = "0" * 32
        elif control == "pidfd-open":
            def unavailable(_pid):
                raise OSError("synthetic pidfd unavailable")
            monkeypatch.setattr(os, "pidfd_open", unavailable)
        elif control == "start-identity":
            original = module.journal.process_start_identity
            starts = []
            def changed_start(pid):
                starts.append(pid)
                return original(pid) if len(starts) == 1 else "synthetic-other-start"
            monkeypatch.setattr(module.journal, "process_start_identity", changed_start)
        elif control == "exe-record":
            record["exe_realpath"] = "/synthetic/other-interpreter"
        elif control == "exe-interpreter":
            original = Path.resolve
            def resolve(path, *args, **kwargs):
                if str(path) == "/proc/self/exe":
                    return Path("/synthetic/other-interpreter")
                return original(path, *args, **kwargs)
            monkeypatch.setattr(Path, "resolve", resolve)
        elif control == "cmdline-digest":
            record["cmdline_sha256"] = "0" * 64
        elif control == "command-policy":
            commands = (("-I", "synthetic-other-launcher"),)
        elif control == "record-lock":
            original = fcntl.fcntl
            def unlocked(fd, command, *args):
                if command == fcntl.F_GETLK:
                    return struct.pack("hhqqi", fcntl.F_UNLCK, os.SEEK_SET, 0, 0, 0)
                return original(fd, command, *args)
            monkeypatch.setattr(fcntl, "fcntl", unlocked)
        if control not in ("record-nofollow",):
            path.write_text(json.dumps(record))
        result = module.cancel_attempt(state_root=case.state, attempt_id=case.envelope["attempt_id"],
            launcher_commands=commands, wait_seconds=.05)
        if control == "pidfd-target":
            assert result == "cancel_pending" and len(sent) == 1 and sent[0][1] == "anon_inode:[pidfd]"
        else:
            assert result == "owner_unverified" and not sent
        assert process.poll() is None
    finally:
        process.terminate()
        _finish_launcher(process)


@pytest.mark.parametrize("control", sorted(CANCEL_CONTROLS))
@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_cancel_source_controls(worker_case, monkeypatch, control, mutated):
    module = _cancel_source_copy(monkeypatch, control) if mutated else worker
    if mutated:
        with pytest.raises(AssertionError):
            _cancel_control_witness(worker_case, monkeypatch, module, control)
    else:
        _cancel_control_witness(worker_case, monkeypatch, module, control)


@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_codex_basename_source_control(worker_case, monkeypatch, mutated):
    import sys
    import types
    from phase_loop_runtime.convergence.adapters import codex
    module = codex
    if mutated:
        source = Path(codex.__file__).read_text()
        old = 'if Path(prepared.view.inputs.executable.path).name != CODEX_EXECUTABLE:'
        assert old in source
        module = types.ModuleType("phase_loop_runtime.convergence.adapters._codex_copy")
        module.__package__, module.__file__ = codex.__package__, codex.__file__
        monkeypatch.setitem(sys.modules, module.__name__, module)
        exec(compile(source.replace(old, 'if False:', 1), module.__file__, "exec"), module.__dict__)
    result = module.run_codex_patch_return(prepare(worker_case),
        config_bytes=worker_case.config.config_path.read_bytes(), state_root=worker_case.state)
    if mutated:
        with pytest.raises(AssertionError):
            assert result.refusal == "provider_mismatch" and not worker_case.state.exists()
    else:
        assert result.refusal == "provider_mismatch" and not worker_case.state.exists()


def test_landed_refusal_then_writer_failure(worker_case, monkeypatch):
    test_real_writer_fault_stops_journal_calls(worker_case, monkeypatch, "terminal", "fsync", prestart=True)


def test_jcs_changed_number_and_unencodable(worker_case):
    case = worker_case
    case.envelope["caller_context"] = {"__proto__": {"number": 1}}
    first = run(case)
    case.envelope["attempt_id"] += "-number"
    case.envelope["caller_context"]["__proto__"]["number"] = 2
    second = run(case)
    assert first.identity.caller_context_sha256 != second.identity.caller_context_sha256
    case.envelope["attempt_id"] += "-large"
    case.envelope["caller_context"] = {"number": 2 ** 60}
    result = run(case)
    assert result.refusal == "caller_context_unencodable" and result.worker_invocations == 0
    root = rs.open_journal_root(case.state / "journal", create=False)
    assert rs.read_attempt(root, case.envelope["attempt_id"]).identity is None


@pytest.mark.parametrize("path", ["../file", "/file", ".git/config", ".GIT/config", "a//b", "./file", "a/../b", "", "x" * 4097], ids=["parent", "absolute", "git", "git-case", "empty-component", "dot", "nested-parent", "empty", "long"])
def test_proposal_normalized_paths(worker_case, path):
    case = worker_case
    case.settings["worker_proposal_cap"] = 100000
    case.config.config_path.write_text(json.dumps(case.settings))
    proposal = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n".encode()
    case.executable.write_text("#!/usr/bin/python3\nimport os\nos.write(1," + repr(proposal) + ")\n")
    assert run(case).proposal.status == "withheld_malformed"


def test_absent_baseline_and_event_cap(worker_case, monkeypatch):
    case = worker_case
    (case.root / "workspace/file").unlink()
    original = rs.open_writer
    dropped = []
    def open_writer(*args, **kwargs):
        real = original(*args, **kwargs)
        class Capped:
            def __getattr__(self, name):
                return getattr(real, name)
            def event(self, phrase, **kwargs):
                dropped.append(phrase)
                return rs.JournalRefused("event_cap_reached")
        return Capped()
    monkeypatch.setattr(rs, "open_writer", open_writer)
    result = run(case)
    assert result.journal_complete and result.journal_anchor and dropped
    assert all(row.git_blob_sha1 is None and row.sha256 is None for row in result.proposal.baselines)


def test_torn_running_append_is_unknown(worker_case, monkeypatch):
    original_open, original_write = rs.open_writer, os.write
    landed = []
    def opened(*args, **kwargs):
        real = original_open(*args, **kwargs)
        class Wrapped:
            def __getattr__(self, name):
                return getattr(real, name)
            def state(self, state, **kwargs):
                if state != "running":
                    return real.state(state, **kwargs)
                def partial(fd, data):
                    path = os.readlink(f"/proc/self/fd/{fd}")
                    if "segments" in path or path.endswith(".jsonl"):
                        original_write(fd, data[:max(1, len(data) // 2)])
                        landed.append(1)
                        raise OSError("synthetic partial append")
                    return original_write(fd, data)
                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(os, "write", partial)
                    return real.state(state, **kwargs)
        return Wrapped()
    monkeypatch.setattr(rs, "open_writer", opened)
    result = run(worker_case)
    assert landed and result.refusal == "journal_unavailable" and result.worker_invocations == 0
    root = rs.open_journal_root(worker_case.state / "journal", create=False)
    observed = projection.attempt_status(root, worker_case.envelope["attempt_id"])
    assert observed.display == "unknown" and "journal_torn_line" in observed.diagnostics


@pytest.mark.parametrize("field", ["workspace", "executable", "wrapper"])
def test_missing_prespawn_identity(worker_case, monkeypatch, field):
    case = worker_case
    if field == "wrapper":
        case.wrapper.write_bytes(b"#!/bin/sh\nexec \"$@\"\n")
        case.envelope["launch_inputs"]["wrappers"] = [str(case.wrapper)]
    original = worker.run_bounded_capture
    def changed(request, *, before_spawn, cancel):
        if field == "workspace":
            (case.root / "workspace").rename(case.root / "workspace-old")
        else:
            (case.executable if field == "executable" else case.wrapper).unlink()
        return original(request, before_spawn=before_spawn, cancel=cancel)
    monkeypatch.setattr(worker, "run_bounded_capture", changed)
    result = run(case)
    assert result.refusal == field + "_changed" and result.worker_invocations == 0


@pytest.mark.parametrize("kind", ["workspace", "target", "references", "mode", "symlink"])
def test_state_root_refusal_has_no_attempt_effects(worker_case, kind):
    case = worker_case
    if kind in ("workspace", "target", "references"):
        case.state = case.root / kind
    elif kind == "mode":
        case.state.mkdir(mode=0o700)
        case.state.chmod(0o755)
    else:
        actual = case.root / "actual-state"
        actual.mkdir(mode=0o700)
        case.state.symlink_to(actual, target_is_directory=True)
    prior = set(case.state.iterdir())
    result = run(case)
    assert result.refusal == "state_root_unsafe" and result.worker_invocations == 0
    assert set(case.state.iterdir()) == prior


@pytest.mark.parametrize("kind", ["refusal", "exception"])
def test_open_writer_failure_preserves_reservation(worker_case, monkeypatch, kind):
    def unavailable(*args, **kwargs):
        if kind == "exception":
            raise RuntimeError("synthetic writer unavailable")
        return rs.JournalRefused("synthetic_writer_unavailable")
    monkeypatch.setattr(rs, "open_writer", unavailable)
    result = run(worker_case)
    assert result.refusal == "journal_unavailable" and not result.journal_complete and result.journal_anchor is None
    assert not (worker_case.state / "evidence").exists() and not (worker_case.state / "launchers").exists()
    root = rs.open_journal_root(worker_case.state / "journal", create=False)
    assert rs.resolve_run(root, worker_case.envelope["run_id"]) == (worker_case.envelope["attempt_id"],)


@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_raised_writer_exception_stops_after_landed_append(worker_case, monkeypatch, exception):
    test_real_writer_fault_stops_journal_calls(worker_case, monkeypatch, "running", "fsync", exception=exception)


@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("site", ["reserve_attempt", "open_writer"])
def test_reservation_and_writer_exception_boundary(worker_case, monkeypatch, exception, site):
    def unavailable(*args, **kwargs):
        raise exception("synthetic journal boundary")
    monkeypatch.setattr(rs, site, unavailable)
    result = run(worker_case)
    assert result.refusal == "journal_unavailable" and not result.journal_complete
    assert result.worker_invocations == 0 and result.journal_anchor is None
    assert not (worker_case.state / "evidence").exists() and not (worker_case.state / "launchers").exists()


def test_evidence_environment_names_match_spawn(worker_case, monkeypatch):
    from phase_loop_runtime import panel_invoker, sandbox_policy
    original = panel_invoker.launch_owned
    supplied = []
    def launch(*args, **kwargs):
        supplied.append(sorted(kwargs["env"]))
        return original(*args, **kwargs)
    monkeypatch.setattr(panel_invoker, "launch_owned", launch)
    result = run(worker_case)
    assert result.state == "finished" and result.proposal.status == "returned"
    record = json.loads((worker_case.state / "evidence" / worker._run(result.identity) / "evidence.json").read_bytes())
    assert supplied == [record["environment_names"]]
    assert sandbox_policy.CHILD_SCRATCH_MARKER in record["environment_names"]
    assert set(record["environment_names"]) <= {"TMPDIR", "CLAUDE_CODE_TMPDIR", sandbox_policy.CHILD_SCRATCH_MARKER}


def _deep_workspace(root):
    import sys
    paths = []
    for _ in range(sys.getrecursionlimit() + 20):
        root = root / "d"
        root.mkdir()
        paths.append(root)
    return paths


@pytest.mark.parametrize("stage", ["before", "after"])
def test_audit_depth_has_a_terminal_result(worker_case, monkeypatch, stage):
    case = worker_case
    paths = []
    original = worker.run_bounded_capture
    def captured(*args, **kwargs):
        result = original(*args, **kwargs)
        paths.extend(_deep_workspace(case.root / "workspace"))
        return result
    try:
        if stage == "before":
            paths.extend(_deep_workspace(case.root / "workspace"))
        else:
            monkeypatch.setattr(worker, "run_bounded_capture", captured)
        result = run(case)
        root = rs.open_journal_root(case.state / "journal", create=False)
        read = rs.read_attempt(root, case.envelope["attempt_id"])
        if stage == "before":
            assert result.refusal == "audit_error" and result.worker_invocations == 0
            assert read.state == "refused" and not (case.state / "evidence").exists()
        else:
            assert result.state == read.state == "finished"
            assert result.proposal.status == "withheld_audit_error"
            assert result.termination.reason == "completed" and result.journal_complete
    finally:
        for path in reversed(paths):
            path.rmdir()


def test_evidence_root_file_has_a_terminal_result(worker_case):
    case = worker_case
    case.state.mkdir(mode=0o700)
    (case.state / "evidence").write_bytes(b"synthetic occupied path")
    result = run(case)
    assert result.state == "finished" and result.proposal.status == "withheld_evidence_error"
    assert result.proposal.proposal_bytes_digest is None and result.proposal.locator is None
    assert result.evidence_envelope_digest is None and result.journal_complete
    root = rs.open_journal_root(case.state / "journal", create=False)
    read = rs.read_attempt(root, case.envelope["attempt_id"])
    assert read.state == "finished" and read.terminal.result_binding is None
    assert not any(json.loads(line)["body"]["refs"] for line in read.lines
                   if json.loads(line)["line_kind"] == "event")


def test_scratch_refusal_is_journalled(worker_case, monkeypatch):
    def unavailable(_allow):
        raise worker.sandbox_policy.SandboxSpaceError("synthetic scratch unavailable")
    monkeypatch.setattr(worker, "worker_child_environment", unavailable)
    result = run(worker_case)
    assert result.refusal == "scratch_unavailable" and result.worker_invocations == 0
    assert result.journal_complete and result.journal_anchor
    root = rs.open_journal_root(worker_case.state / "journal", create=False)
    assert rs.read_attempt(root, worker_case.envelope["attempt_id"]).terminal.refusal.reason == "scratch_unavailable"
    assert not (worker_case.state / "evidence").exists()


def test_environment_is_built_once_for_capture_and_evidence(worker_case, monkeypatch):
    original = worker.worker_child_environment
    calls = []
    def environment(allow):
        calls.append(1)
        mapping = original(allow)
        mapping[f"WORKER_FIXTURE_ENV_{len(calls)}"] = "synthetic"
        return mapping
    monkeypatch.setattr(worker, "worker_child_environment", environment)
    result = run(worker_case)
    assert result.state == "finished" and calls == [1]
    evidence = json.loads((worker_case.state / "evidence" / worker._run(result.identity) / "evidence.json").read_bytes())
    assert "WORKER_FIXTURE_ENV_1" in evidence["environment_names"]


@pytest.mark.parametrize("relative", ["HEAD", "packed-refs", "refs", "refs/branch"])
def test_target_ref_links_refuse_before_capture(worker_case, relative):
    case = worker_case
    path = case.root / "target/.git" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(case.root / "references")
    result = run(case)
    assert result.refusal == "audit_error" and result.worker_invocations == 0
    assert not (case.state / "evidence").exists()


@pytest.mark.parametrize("header", ["rename from", "rename to", "copy from", "copy to"])
@pytest.mark.parametrize("path", [".git/config", "../outside", "/absolute"])
def test_extended_proposal_paths_are_normalized(worker_case, header, path):
    proposal = f"diff --git a/file b/file\n{header} {path}\n".encode()
    worker_case.executable.write_text("#!/usr/bin/python3\nimport os\nos.write(1," + repr(proposal) + ")\n")
    result = run(worker_case)
    assert result.proposal.status == "withheld_malformed" and result.proposal.proposal_bytes_digest is None


def test_extended_proposal_paths_supply_baselines(worker_case):
    proposal = b"diff --git a/file b/file\nrename from old\nrename to new\ncopy from source\ncopy to dest\n"
    worker_case.executable.write_text("#!/usr/bin/python3\nimport os\nos.write(1," + repr(proposal) + ")\n")
    result = run(worker_case)
    assert result.proposal.status == "returned"
    assert [row.path for row in result.proposal.baselines] == ["file", "old", "new", "source", "dest"]


@pytest.mark.parametrize("error", [OSError, ValueError])
def test_retirement_marks_continue_after_one_failure(worker_case, monkeypatch, error):
    case = worker_case
    first = run(case)
    case.envelope["attempt_id"] += "-second"
    run(case)
    registry = case.state / "evidence" / worker.retention.REGISTRY / (worker._run(first.identity) + ".json")
    completed = json.loads(registry.read_bytes())["completed_at"]
    original_prune, original_write = worker.retention.prune, worker._write
    attempted = []
    def prune(root, **kwargs):
        return original_prune(root, **kwargs, now=completed + 100 * 86400)
    def write(path, data):
        if path.suffix == ".retired":
            attempted.append(path)
            if len(attempted) == 1:
                raise error("synthetic retirement mark")
        return original_write(path, data)
    monkeypatch.setattr(worker.retention, "prune", prune)
    monkeypatch.setattr(worker, "_write", write)
    case.envelope["attempt_id"] += "-third"
    result = run(case)
    assert result.state == "finished" and len(attempted) >= 2
    assert not attempted[0].exists() and all(path.exists() for path in attempted[1:])


@pytest.mark.parametrize("site", ["record", "lock"])
def test_launcher_record_refusal_reason(worker_case, monkeypatch, site):
    if site == "record":
        original = worker._write
        def write(path, data):
            if path.parent.name == "launchers":
                raise OSError("synthetic launcher record")
            return original(path, data)
        monkeypatch.setattr(worker, "_write", write)
    else:
        def lock(*args):
            raise OSError("synthetic launcher lock")
        monkeypatch.setattr(worker.fcntl, "lockf", lock)
    result = run(worker_case)
    assert result.refusal == "launcher_record_unavailable" and result.worker_invocations == 0
    root = rs.open_journal_root(worker_case.state / "journal", create=False)
    read = rs.read_attempt(root, worker_case.envelope["attempt_id"])
    assert read.state == "refused" and read.terminal.refusal.reason == "launcher_record_unavailable"


def test_launcher_signal_handler_spans_record_lifetime(worker_case, monkeypatch):
    import signal
    original_handler = signal.getsignal(signal.SIGTERM)
    original_write, original_close = worker._write, os.close
    closed = []
    def write(path, data):
        if path.parent.name == "launchers":
            handler = signal.getsignal(signal.SIGTERM)
            assert handler != original_handler and callable(handler)
            handler(signal.SIGTERM, None)
        return original_write(path, data)
    def close(fd):
        if "/launchers/" in os.readlink(f"/proc/self/fd/{fd}"):
            closed.append(signal.getsignal(signal.SIGTERM))
        return original_close(fd)
    monkeypatch.setattr(worker, "_write", write)
    monkeypatch.setattr(os, "close", close)
    result = run(worker_case)
    assert result.refusal == "cancelled_before_start" and closed
    assert all(handler != original_handler for handler in closed)
    assert signal.getsignal(signal.SIGTERM) == original_handler


from test_supervised_launch_binding import v2_operator
from test_supervised_capture_v2 import build_v2_attempt
from test_supervised_contracts_vectors import V2_CORPUS, expand_v2


def run_v2_attempt(attempt):
    state = attempt.operator.path.parent / "worker-state"
    config = dict(attempt.binding.snapshots)[attempt.binding.spec.config_path]
    return worker.run_patch_return(attempt.prepared, config_bytes=config, state_root=state), state


@pytest.mark.parametrize("case_record", [row for row in V2_CORPUS if row["kind"] == "echo"], ids=lambda row: row["id"])
def test_v2_published_echo_at_real_writer_and_reader(v2_operator, case_record):
    import rfc8785
    value = expand_v2(case_record)
    payload = value["envelope"]["caller_context"]
    attempt = build_v2_attempt(v2_operator, caller_context=payload)
    assert attempt.prepared.view.inputs.spawn_capability is None
    result, state = run_v2_attempt(attempt)
    assert result.state == "finished" and result.journal_complete, result
    assert result.identity.run_id == v2_operator.attempt.run_id and result.identity.attempt_id == v2_operator.attempt.attempt_id
    root = rs.open_journal_root(state / "journal", create=False)
    status = projection.attempt_status(root, result.identity.attempt_id)
    view = projection.build_v2_reader_view(root,
        dict(assignment_digest=result.identity.assignment_digest, snapshot_ref=result.identity.snapshot_ref), status, state_root=state)
    assert isinstance(view, projection.V2ReaderView), view
    expected = rfc8785.dumps(payload)
    assert view.caller_context_bytes == expected
    from phase_loop_runtime.supervised_contracts import load_contract_bundle, validate_record
    validate_record(load_contract_bundle(version="v2"), "supervised_run_status.v1", view.status_bytes, definition="reader_view")
    if case_record["expected"]:
        assert view.caller_context_bytes != rfc8785.dumps(value["echoed_caller_context"])
    else:
        assert view.caller_context_bytes == rfc8785.dumps(value["echoed_caller_context"])
    (state / "echo" / result.identity.caller_context_sha256).write_bytes(b"altered")
    assert projection.build_v2_reader_view(root,
        dict(assignment_digest=result.identity.assignment_digest, snapshot_ref=result.identity.snapshot_ref), status,
        state_root=state) == rs.JournalRefused("echo_unavailable")


def test_v2_worker_recheck_refuses_before_spawn(v2_operator, monkeypatch):
    attempt = build_v2_attempt(v2_operator)
    path = attempt.binding.spec.references[0][1].path
    path.write_bytes(path.read_bytes() + b"changed")
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected spawn")
    monkeypatch.setattr(worker, "run_bounded_capture", forbidden)
    result, state = run_v2_attempt(attempt)
    assert result.state == "refused" and result.worker_invocations == 0
    assert not (state / "journal").exists()
    assert attempt.capture._closed


def test_v2_public_status_is_unknown_without_acknowledged_anchor():
    result = worker.WorkerResult(None, "refused", None, "binding_invalid", 0, None, None, None, False)
    mapped = projection.v2_status_mapping(result)
    assert mapped.runtime_state == "unknown" and mapped.public_status_bytes is None and not mapped.journal_acknowledged


@pytest.mark.parametrize("stage", ["before-link", "after-link", "equal", "concurrent", "conflict"])
def test_v2_echo_publication_lifetime(tmp_path, monkeypatch, stage):
    from phase_loop_runtime import supervised_echo as echo
    tmp_path.chmod(0o700)
    payload = b'{"fixture":"opaque"}'
    digest = sha256(payload).hexdigest()
    if stage in {"before-link", "after-link"}:
        original = echo.os.fsync
        calls = []
        def sync(fd):
            calls.append(fd)
            if len(calls) == (1 if stage == "before-link" else 2):
                raise OSError()
            return original(fd)
        monkeypatch.setattr(echo.os, "fsync", sync)
        assert echo.write_echo(tmp_path, payload) == echo.EchoRefused()
        assert not list((tmp_path / "echo").glob(".echo-*"))
        if stage == "after-link": assert echo.read_echo(tmp_path, digest) == payload
        else: assert echo.read_echo(tmp_path, digest) == echo.EchoRefused()
    elif stage == "concurrent":
        results = []
        threads = [threading.Thread(target=lambda: results.append(echo.write_echo(tmp_path, payload))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads) and results == [digest, digest]
        assert echo.read_echo(tmp_path, digest) == payload
    else:
        assert echo.write_echo(tmp_path, payload) == digest
        if stage == "conflict": (tmp_path / "echo" / digest).write_bytes(b"different")
        assert echo.write_echo(tmp_path, payload) == (echo.EchoRefused() if stage == "conflict" else digest)
        assert (tmp_path / "echo" / digest).read_bytes() == (b"different" if stage == "conflict" else payload)


def test_v2_status_mapping_closed_table_through_real_result(v2_operator):
    from dataclasses import replace
    from types import SimpleNamespace
    from phase_loop_runtime.supervised_contracts import load_contract_bundle, validate_record
    attempt = build_v2_attempt(v2_operator)
    result, _state = run_v2_attempt(attempt)
    assert result.state == "finished"
    bundle = load_contract_bundle(version="v2")
    for code in sorted(projection.V2_REFUSAL_REASONS):
        mapped = projection.v2_status_mapping(replace(result, state="refused", termination=None, refusal=code))
        assert mapped.runtime_state == "refused" and mapped.refusal == code and mapped.journal_acknowledged
        validate_record(bundle, "supervised_run_status.v1", mapped.public_status_bytes, definition="reader_view")
    for runtime in projection.RUNTIME_STATES:
        if runtime in {"unknown", "stale_unknown"}: continue
        state = "finished" if runtime.startswith("finished (") else runtime
        reason = runtime[len("finished ("):-1] if state == "finished" else None
        mapped = projection.v2_status_mapping(replace(result, state=state, refusal=None,
            termination=SimpleNamespace(reason=reason) if reason else None))
        assert mapped.runtime_state == runtime and mapped.journal_acknowledged
        validate_record(bundle, "supervised_run_status.v1", mapped.public_status_bytes, definition="reader_view")
    for changed in (replace(result, journal_complete=False), replace(result, journal_anchor=None),
                    replace(result, identity=None), replace(result, refusal="unlisted-local-code")):
        mapped = projection.v2_status_mapping(changed)
        assert mapped.runtime_state == "unknown" and not mapped.journal_acknowledged and mapped.public_status_bytes is None
