"""Synthetic WORKER tests exercise landed admission and JOURNAL."""
from dataclasses import replace
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
        qualify(case)
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
        case.settings["worker_audit_entry_cap" if kind == "entries" else "worker_audit_byte_cap"] = 1
        case.config.config_path.write_text(json.dumps(case.settings))
    result = run(case)
    assert result.refusal == "audit_error" and not (case.state / "evidence").exists()


def test_retention_identity_and_unrecorded_deletion(worker_case, monkeypatch):
    import shutil
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
