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
