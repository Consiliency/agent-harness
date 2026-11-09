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
def test_real_writer_fault_stops_journal_calls(worker_case, monkeypatch, phase, operation):
    case = worker_case
    original_open = rs.open_writer
    original_io = getattr(os, operation)
    calls, failed = [], []
    def opened(*args, **kwargs):
        real = original_open(*args, **kwargs)
        class Delegating:
            def __getattr__(self, name):
                method = getattr(real, name)
                if name == "close":
                    return method
                def invoke(*a, **kw):
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
                            raise OSError("synthetic journal I/O")
                        return original_io(fd, *rest)
                    with pytest.MonkeyPatch.context() as patch:
                        patch.setattr(os, operation, fault)
                        return method(*a, **kw)
                return invoke
        return Delegating()
    monkeypatch.setattr(rs, "open_writer", opened)
    result = run(case)
    assert failed, calls
    assert not result.journal_complete and result.journal_anchor is None
    assert result.worker_invocations == (0 if phase in ("queued", "running") else 1)
    if not result.worker_invocations:
        assert result.refusal == "journal_unavailable" and not (case.state / "evidence").exists()


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


@pytest.mark.parametrize("kind", ["fifo", "gitfile", "entries", "bytes"])
def test_before_audit_refusal(worker_case, kind):
    case = worker_case
    if kind == "fifo":
        os.mkfifo(case.root / "workspace/fifo")
    elif kind == "gitfile":
        (case.root / "target/.git").write_text("gitdir: /elsewhere")
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
