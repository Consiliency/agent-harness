"""v13 LANEEXEC SL-2: return, status and cancel mapping.

Obligation C8 of the frozen wire artifact as narrowed by binding artifact §3 L-S5, and the
§3 L-S4 status and cancel tables, checked as closed, exhaustive tables. Every case enters
through the production functions of ``launch_return``.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import itertools
import json
import os
from pathlib import Path
import stat
import time
import typing
import zlib

import pytest

from phase_loop_runtime import launch_process_contract as contract
from phase_loop_runtime import launch_return as lr
from phase_loop_runtime import openshell_artifacts
from phase_loop_runtime import run_status
from phase_loop_runtime import run_status_projection as projection
from phase_loop_runtime.convergence.adapters import patch_return

SENTINEL = b"RAW-OUTPUT-SENTINEL-7f3c"
COMMIT = "c" * 40
HEX = "b" * 64
DIGEST = "sha256:" + "a" * 64
LIMITS = openshell_artifacts.Limits(source_bytes=1 << 20, file_bytes=1 << 20, files=100,
                                    patch_bytes=1 << 20, output_bytes=1 << 20)
POLICY = lr.ReturnPolicy(binary_limits=LIMITS)
LANDED_PROPOSAL_STATUSES = ("returned", "absent", "withheld_incomplete", "withheld_oversized",
                            "withheld_malformed", "withheld_audit_error",
                            "withheld_unexplained_change", "withheld_evidence_error")


def bound(seconds: float = 30.0, cancelled=lambda: False) -> openshell_artifacts.Bound:
    return openshell_artifacts.Bound(time.monotonic() + seconds, cancelled)


def patch_bytes(path: str = "src/app.py") -> bytes:
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n"
            f"-old\n+new {SENTINEL.decode()}\n").encode()


def worker(proposal, *, reason="completed"):
    return patch_return.WorkerResult(None, "finished",
                                     run_status.Termination(reason, None, "worker"), None, 1,
                                     proposal, None, None, False)


@pytest.fixture
def state(tmp_path):
    os.chmod(tmp_path, 0o700)
    evidence = tmp_path / "worker" / "evidence"
    (evidence / "a-run").mkdir(parents=True, mode=0o700)
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    laneexec = tmp_path / "laneexec"
    laneexec.mkdir(mode=0o700)
    return {"evidence": evidence, "out": out, "return_dir": laneexec / "rsv-1"}


def store_proposal(state, data: bytes, *, baselines=(), digest=None, status="returned",
                   byte_length=None):
    (state["evidence"] / "a-run" / "proposal.bin").write_bytes(data)
    return patch_return.ProposalReturn(
        status, sha256(data).hexdigest() if digest is None else digest,
        len(data) if byte_length is None else byte_length,
        tuple(patch_return.BaselineIdentity(p, None, None) for p in baselines), "a-run/proposal.bin")


def attempt(state, proposal=None, *, reason="completed", masks=(), mask_dirs=(), out=True):
    return lr.ReturnAttempt(return_dir=state["return_dir"],
                            worker_result=None if proposal is None else worker(proposal, reason=reason),
                            evidence_root=state["evidence"], out_dir=state["out"] if out else None,
                            base_commit=COMMIT, masks=tuple(masks), mask_dirs=tuple(mask_dirs))


def returned_files(state):
    directory = state["return_dir"]
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def assert_no_raw(outcome):
    text = repr(outcome) + json.dumps(outcome.evidence())
    if outcome.descriptor is not None:
        text += json.dumps(outcome.descriptor.to_json())
    assert SENTINEL.decode() not in text


# -- L-S5 patch rows ------------------------------------------------------------------------

def test_proposal_status_table_is_the_landed_vocabulary():
    assert tuple(lr.PROPOSAL_STATUS_TABLE) == LANDED_PROPOSAL_STATUSES
    assert lr.PROPOSAL_STATUS_TABLE == {
        "returned": None, "absent": None, "withheld_incomplete": None,
        "withheld_oversized": "sandbox_launch_result_invalid",
        "withheld_malformed": "sandbox_launch_result_invalid",
        "withheld_audit_error": "sandbox_launch_audit_failed",
        "withheld_unexplained_change": "sandbox_launch_audit_failed",
        "withheld_evidence_error": "sandbox_launch_audit_failed",
    }


@pytest.mark.parametrize("status", [s for s in LANDED_PROPOSAL_STATUSES if s != "returned"])
def test_every_non_returned_status_returns_null_with_its_code(state, status):
    proposal = patch_return.ProposalReturn(status, None, 0, (), None)
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=POLICY, withhold=None,
                                bound=bound())
    assert outcome.descriptor is None
    assert outcome.code == lr.PROPOSAL_STATUS_TABLE[status]
    assert outcome.status == status
    assert returned_files(state) == []


@pytest.mark.parametrize("reason", ["cancelled", "timed_out", "failed_to_start"])
def test_non_completed_termination_withheld_incomplete_returns_null_no_code(state, reason):
    # WORKER withholds every non-completed termination; a proposal file present is ignored.
    store_proposal(state, patch_bytes())
    proposal = patch_return.ProposalReturn("withheld_incomplete", None, 10, (), None)
    outcome = lr.collect_return(attempt(state, proposal, reason=reason), "patch", policy=POLICY,
                                withhold=None, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, None)
    assert returned_files(state) == []


def test_unknown_proposal_status_fails_closed(state):
    proposal = patch_return.ProposalReturn("returned_partially", None, 0, (), None)
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_audit_failed")


def test_no_worker_result_is_null(state):
    outcome = lr.collect_return(attempt(state), "patch", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, None)


def test_returned_patch_is_written_once_0600_in_0700_and_schema_valid(state):
    data = patch_bytes()
    outcome = lr.collect_return(attempt(state, store_proposal(state, data, baselines=("src/app.py",))),
                                "patch", policy=POLICY, withhold=None, bound=bound())
    assert outcome.code is None
    descriptor = outcome.descriptor
    assert descriptor.kind == "patch" and descriptor.format == "worker_proposal_bytes"
    assert descriptor.sha256 == sha256(data).hexdigest() and descriptor.byte_length == len(data)
    assert descriptor.base_commit == COMMIT
    path = Path(descriptor.path)
    assert path.parent == state["return_dir"]
    assert path.read_bytes() == data
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert descriptor.to_json()["directory_mode"] == "0700"
    assert descriptor.to_json()["file_mode"] == "0600"
    assert contract.validate_launch_message("ReturnDescriptor", descriptor.to_json())
    assert_no_raw(outcome)
    # Written once: a second collection into the same directory refuses rather than overwrite.
    again = lr.collect_return(attempt(state, store_proposal(state, data)), "patch", policy=POLICY,
                              withhold=None, bound=bound())
    assert (again.descriptor, again.code) == (None, "sandbox_launch_result_invalid")
    assert path.read_bytes() == data


def test_returned_patch_inside_a_finished_launch_response_encodes(state):
    outcome = lr.collect_return(attempt(state, store_proposal(state, patch_bytes())), "patch",
                                policy=POLICY, withhold=None, bound=bound())
    evidence = lr.build_launch_evidence(
        snapshot=None, launch_digest=HEX, template_sha256=HEX, image_digest=DIGEST,
        policy_digest=DIGEST, egress_sha256=DIGEST, transport_id="t-1", caps_sha256=HEX,
        bridge_attached=False, stdout_sha256=sha256(SENTINEL).hexdigest(),
        stderr_sha256=None, exit_status=0, duration_ms=5, renewals=0)
    response = contract.LaunchResponse(
        "req-1", "rsv-1", "att-1", "finished", None, None, None, None,
        contract.Termination("completed", None, "worker"), 1, HEX, "/scratch/att-1",
        "/work/att-1/fs/repo", outcome.descriptor, evidence, {})
    line = contract.encode_launch_response(response)
    assert SENTINEL not in line


@pytest.mark.parametrize("baseline,masks,mask_dirs", [
    ("secrets/key.pem", ("secrets/key.pem",), ()),
    ("private/a/b.txt", (), ("private",)),
    ("private", (), ("private",)),
])
def test_masked_baseline_path_is_audit_failed(state, baseline, masks, mask_dirs):
    proposal = store_proposal(state, patch_bytes(baseline), baselines=("src/app.py", baseline))
    outcome = lr.collect_return(attempt(state, proposal, masks=masks, mask_dirs=mask_dirs),
                                "patch", policy=POLICY, withhold=None, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_audit_failed")
    assert returned_files(state) == []


def test_mask_dir_prefix_is_segment_bound(state):
    proposal = store_proposal(state, patch_bytes("privateer/x"), baselines=("privateer/x",))
    outcome = lr.collect_return(attempt(state, proposal, mask_dirs=("private",)), "patch",
                                policy=POLICY, withhold=None, bound=bound())
    assert outcome.code is None and outcome.descriptor is not None


def test_digest_mismatch_at_the_locator_is_audit_failed(state):
    data = patch_bytes()
    proposal = store_proposal(state, data, digest=sha256(b"other").hexdigest())
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_audit_failed")
    assert returned_files(state) == []
    assert_no_raw(outcome)


@pytest.mark.parametrize("locator", ["/abs/proposal.bin", "../a-run/proposal.bin",
                                     "a-run//proposal.bin", "", None, "a-run/missing.bin"])
def test_unusable_locator_is_audit_failed(state, locator):
    data = patch_bytes()
    store_proposal(state, data)
    proposal = patch_return.ProposalReturn("returned", sha256(data).hexdigest(), len(data), (),
                                           locator)
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_audit_failed")


def test_symlinked_locator_is_never_followed(state, tmp_path):
    target = tmp_path / "elsewhere.bin"
    target.write_bytes(patch_bytes())
    link = state["evidence"] / "a-run" / "proposal.bin"
    link.symlink_to(target)
    proposal = patch_return.ProposalReturn("returned", sha256(target.read_bytes()).hexdigest(),
                                           target.stat().st_size, (), "a-run/proposal.bin")
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_audit_failed")


def test_patch_over_the_laneexec_cap_is_result_invalid(state):
    data = patch_bytes()
    policy = lr.ReturnPolicy(binary_limits=LIMITS, patch_cap=len(data) - 1)
    outcome = lr.collect_return(attempt(state, store_proposal(state, data)), "patch",
                                policy=policy, withhold=None, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    # A dishonest byte_length under the cap still cannot carry more than the cap.
    outcome = lr.collect_return(attempt(state, store_proposal(state, data, byte_length=1)),
                                "patch", policy=policy, withhold=None, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")


@pytest.mark.parametrize("cap", [-1, True])
def test_patch_cap_rejects_invalid_values(cap):
    with pytest.raises(lr.LaunchReturnError) as error:
        lr.ReturnPolicy(binary_limits=LIMITS, patch_cap=cap)
    assert error.value.code == "return_policy_invalid"
    assert lr.ReturnPolicy(binary_limits=LIMITS).patch_cap == 67108864


@pytest.mark.parametrize("cap", [-1, True, 1.5])
def test_result_cap_rejects_invalid_values(cap):
    with pytest.raises(lr.LaunchReturnError) as error:
        lr.ReturnPolicy(binary_limits=LIMITS, result_cap=cap)
    assert error.value.code == "return_policy_invalid"


def test_return_policy_clamps_each_cap_to_its_ceiling():
    policy = lr.ReturnPolicy(LIMITS, patch_cap=lr.PATCH_CAP_MAX + 1, result_cap=lr.RESULT_CAP + 1)
    assert policy.patch_cap == lr.PATCH_CAP_MAX
    assert policy.result_cap == lr.RESULT_CAP
    assert lr.ReturnPolicy(LIMITS).result_cap == lr.RESULT_CAP


@pytest.mark.parametrize("byte_length", [None, 0], ids=["declared-size", "read-size"])
def test_zero_patch_cap_refuses_nonempty_proposal(state, byte_length):
    proposal = store_proposal(state, patch_bytes(), byte_length=byte_length)
    policy = lr.ReturnPolicy(LIMITS, patch_cap=0)
    seen = []
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=policy,
                                withhold=seen.append, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert seen == []
    assert not state["return_dir"].exists()


def test_zero_patch_cap_preserves_verified_absence(state):
    proposal = patch_return.ProposalReturn("absent", None, 0, (), None)
    policy = lr.ReturnPolicy(LIMITS, patch_cap=0)
    seen = []
    outcome = lr.collect_return(attempt(state, proposal), "patch", policy=policy,
                                withhold=seen.append, bound=bound())
    assert (outcome.status, outcome.descriptor, outcome.code) == ("absent", None, None)
    assert seen == []
    assert not state["return_dir"].exists()


@pytest.mark.parametrize("cap", [0, 1], ids=["zero", "lowered"])
def test_result_cap_refuses_nonempty_json_above_cap(state, cap):
    (state["out"] / "result.json").write_bytes(b"{}")
    policy = lr.ReturnPolicy(LIMITS, result_cap=cap)
    seen = []
    outcome = lr.collect_return(attempt(state), "result", policy=policy,
                                withhold=seen.append, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert seen == []
    assert not state["return_dir"].exists()


@pytest.mark.parametrize("kind", ["patch", "result"])
def test_return_at_lowered_kind_cap_is_delivered_with_other_cap_zero(state, kind):
    patch = patch_bytes()
    result = b'{"ok": true}'
    proposal = store_proposal(state, patch)
    (state["out"] / "result.json").write_bytes(result)
    policy = lr.ReturnPolicy(LIMITS, patch_cap=len(patch) if kind == "patch" else 0,
                             result_cap=len(result) if kind == "result" else 0)
    data = patch if kind == "patch" else result
    seen = []

    def withhold(candidate):
        seen.append(candidate)
        return False

    outcome = lr.collect_return(attempt(state, proposal), kind, policy=policy,
                                withhold=withhold, bound=bound())
    assert outcome.code is None
    assert outcome.descriptor.kind == kind
    assert outcome.descriptor.byte_length == len(data)
    assert Path(outcome.descriptor.path).read_bytes() == data
    assert seen == [data]


def test_binary_literal_over_its_limit_is_result_invalid(state):
    payload = zlib.compress(b"x" * 4096)
    line = bytes([ord("A") + min(len(payload), 26) - 1]) + base64.b85encode(payload[:26])
    data = patch_bytes() + b"GIT binary patch\nliteral 4096\n" + line + b"\n\n"
    small = openshell_artifacts.Limits(source_bytes=1 << 20, file_bytes=16, files=10,
                                       patch_bytes=1 << 20, output_bytes=1 << 20)
    outcome = lr.collect_return(attempt(state, store_proposal(state, data)), "patch",
                                policy=lr.ReturnPolicy(binary_limits=small), withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")


def test_exhausted_return_budget_returns_null(state):
    outcome = lr.collect_return(attempt(state, store_proposal(state, patch_bytes())), "patch",
                                policy=POLICY, withhold=None, bound=bound(seconds=-1))
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert returned_files(state) == []


# -- withhold -------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["patch", "result"])
@pytest.mark.parametrize("predicate", [lambda data: True, lambda data: 1, lambda data: None,
                                       lambda data: (_ for _ in ()).throw(RuntimeError())])
def test_withhold_deletes_the_returned_bytes(state, kind, predicate):
    (state["out"] / "result.json").write_bytes(b'{"ok": "' + SENTINEL + b'"}')
    item = attempt(state, store_proposal(state, patch_bytes()))
    seen = []

    def withhold(data):
        seen.append(SENTINEL in data)
        return predicate(data)

    outcome = lr.collect_return(item, kind, policy=POLICY, withhold=withhold, bound=bound())
    assert seen == [True]
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_withheld")
    assert returned_files(state) == []
    assert_no_raw(outcome)


@pytest.mark.parametrize("kind", ["patch", "result"])
def test_withhold_false_delivers(state, kind):
    (state["out"] / "result.json").write_bytes(b'{"ok": true}')
    item = attempt(state, store_proposal(state, patch_bytes()))
    outcome = lr.collect_return(item, kind, policy=POLICY, withhold=lambda data: False,
                                bound=bound())
    assert outcome.code is None and outcome.descriptor.kind == kind


# -- result.json ----------------------------------------------------------------------------

def test_result_json_is_returned_as_json_object(state):
    body = b'{"ok": true, "note": "' + SENTINEL + b'", "truncated": false}\n'
    (state["out"] / "result.json").write_bytes(body)
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    descriptor = outcome.descriptor
    assert outcome.code is None
    assert (descriptor.kind, descriptor.format, descriptor.base_commit) == ("result", "json_object", None)
    assert Path(descriptor.path).read_bytes() == body
    assert stat.S_IMODE(Path(descriptor.path).stat().st_mode) == 0o600
    assert contract.validate_launch_message("ReturnDescriptor", descriptor.to_json())
    assert_no_raw(outcome)


def test_result_json_at_the_bound_is_accepted_and_over_it_refused(state):
    head = b'{"pad": "'
    tail = b'"}'
    body = head + b"x" * (lr.RESULT_CAP - len(head) - len(tail)) + tail
    assert len(body) == 1048576
    (state["out"] / "result.json").write_bytes(body)
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    assert outcome.code is None and outcome.descriptor.byte_length == 1048576
    os.unlink(outcome.descriptor.path)
    (state["out"] / "result.json").write_bytes(body + b" ")
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")


@pytest.mark.parametrize("body", [
    b'{"a": 1, "a": 2}',
    b'{"a": 1} {"b": 2}',
    b'{"a": 1}x',
    b'{"truncated": true}',
    b'{"truncated": 0}',
    b'{"truncated": null}',
    b'{"n": NaN}',
    b'{"n": Infinity}',
    b'{"n": 1e999}',
    b'[1, 2]',
    b'"text"',
    b'',
    b'\xef\xbb\xbf{}',
    b'{"s": "\xff"}',
    b'{"nested": {"a": 1, "a": 1}}',
])
def test_result_json_strictness(state, body):
    (state["out"] / "result.json").write_bytes(body)
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert returned_files(state) == []


def test_result_json_missing_or_symlinked_is_invalid(state, tmp_path):
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    assert outcome.code == "sandbox_launch_result_invalid"
    target = tmp_path / "t.json"
    target.write_bytes(b"{}")
    (state["out"] / "result.json").symlink_to(target)
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")


def test_unreachable_out_directory_returns_null_without_code(state):
    outcome = lr.collect_return(attempt(state, out=False), "result", policy=POLICY,
                                withhold=None, bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, None)


def test_none_returns_null_and_unknown_kind_refuses(state):
    (state["out"] / "result.json").write_bytes(b"{}")
    outcome = lr.collect_return(attempt(state, store_proposal(state, patch_bytes())), "none",
                                policy=POLICY, withhold=lambda d: pytest.fail("called"),
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, None)
    assert returned_files(state) == []
    with pytest.raises(lr.LaunchReturnError):
        lr.collect_return(attempt(state), "tarball", policy=POLICY, withhold=None, bound=bound())


def test_return_dir_with_wrong_mode_refuses(state):
    state["return_dir"].mkdir(mode=0o755)
    os.chmod(state["return_dir"], 0o755)
    (state["out"] / "result.json").write_bytes(b"{}")
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=bound())
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert returned_files(state) == []


# -- LaunchEvidence -------------------------------------------------------------------------

def evidence_fields(**changes):
    fields = dict(snapshot=None, launch_digest=HEX, template_sha256=HEX, image_digest=DIGEST,
                  policy_digest=DIGEST, egress_sha256=DIGEST, transport_id="t-1",
                  caps_sha256=None, bridge_attached=True, stdout_sha256=HEX, stderr_sha256=HEX,
                  exit_status=-9, duration_ms=0, renewals=3)
    fields.update(changes)
    return fields


def test_launch_evidence_builder_is_metadata_only():
    record = lr.build_launch_evidence(**evidence_fields())
    assert contract.validate_launch_message("LaunchEvidence", record.to_json())


@pytest.mark.parametrize("changes", [
    {"stdout_sha256": SENTINEL.decode()}, {"stderr_sha256": "B" * 64},
    {"template_sha256": "sha256:" + HEX}, {"image_digest": HEX}, {"exit_status": 256},
    {"duration_ms": -1}, {"renewals": True}, {"bridge_attached": 1}, {"transport_id": ""},
])
def test_launch_evidence_builder_refuses_non_metadata(changes):
    with pytest.raises(lr.LaunchReturnError) as error:
        lr.build_launch_evidence(**evidence_fields(**changes))
    assert error.value.code == "evidence_invalid"
    assert SENTINEL.decode() not in str(error.value)


# -- L-S4 worker terminal ---------------------------------------------------------------------

def test_worker_terminal_table_is_closed_over_runtime_states():
    expected = {
        "finished (completed)": ("finished", "completed"),
        "finished (cancelled)": ("finished", "cancelled"),
        "finished (timed_out)": ("finished", "timed_out"),
        "finished (failed_to_start)": ("finished", "failed_to_start"),
        "refused": ("finished", "failed_to_start"),
        "queued": ("uncertain", None), "running": ("uncertain", None),
        "cancelling": ("uncertain", None), "unknown": ("uncertain", None),
        "stale_unknown": ("uncertain", None),
    }
    assert set(expected) == set(projection.RUNTIME_STATES)
    for runtime_state, (state, reason) in expected.items():
        mapped = lr.map_worker_terminal(runtime_state)
        assert mapped.state == state
        assert (None if mapped.termination is None else mapped.termination.reason) == reason
    assert lr.map_worker_terminal(None) == lr.TerminalMapping(
        "finished", contract.Termination("failed_to_start", None, "harness"))
    for other in ("finished", "finished (lost)", "", 7):
        assert lr.map_worker_terminal(other).state == "uncertain"


def test_worker_terminal_keeps_matching_worker_termination():
    termination = contract.Termination("cancelled", "SIGTERM", "operator")
    assert lr.map_worker_terminal("finished (cancelled)", termination).termination == termination
    mismatched = lr.map_worker_terminal("finished (completed)", termination).termination
    assert mismatched == contract.Termination("completed", None, "harness")


def _identity():
    return patch_return.WorkerAttemptIdentity("a" * 64, "b" * 64, "c" * 64, "d" * 64, "run-1",
                                              "att-1", ("u1",), (), "9" * 64, "e" * 64)


@pytest.mark.parametrize("state,refusal,expected", [
    ("finished", None, ("finished", "completed")),
    ("refused", "cancelled_before_start", ("finished", "failed_to_start")),
])
def test_worker_result_through_closeout_mapping(state, refusal, expected):
    termination = run_status.Termination("completed", None, "worker") if state == "finished" else None
    result = patch_return.WorkerResult(_identity(), state, termination, refusal, 1, None, None,
                                       patch_return.JournalAnchor(3, "f" * 64), True)
    mapped = lr.map_worker_result(result)
    assert (mapped.state, mapped.termination.reason) == expected


def test_unacknowledged_worker_result_is_uncertain():
    result = patch_return.WorkerResult(_identity(), "finished",
                                       run_status.Termination("completed", None, "worker"), None,
                                       1, None, None, None, False)
    assert lr.map_worker_result(result) == lr.TerminalMapping("uncertain", None)
    assert lr.map_worker_result(None).termination.reason == "failed_to_start"


# -- L-S4 status table ------------------------------------------------------------------------

def journal(display, *, identity=True):
    state = display if display in ("queued", "running", "cancelling") else (
        None if display == "unknown" else "finished")
    return projection.AttemptStatus(
        "att-1", state, display, None, None, None, None, (),
        run_status.AttemptIdentity("a" * 64, "b" * 64, "run-1", "att-1") if identity else None)


def terminal(state):
    termination = contract.Termination("completed", None, "worker") if state == "finished" else None
    code = {"finished": None, "refused": "sandbox_launch_refused",
            "uncertain": lr.STATUS_UNCERTAIN_CODE}[state]
    return contract.LaunchResponse("req-1", "rsv-1", "att-1", state, code, None, None, None,
                                   termination, 1 if state == "finished" else 0, None, None,
                                   None, None, None, {})


def expected_status(record, launch, display, identity, claim):
    if not record:
        return "unknown_attempt"
    if launch is not None:
        return launch
    if display in ("queued", "running", "cancelling") and identity:
        return display
    return "uncertain"


def test_status_table_is_closed_and_exhaustive():
    displays = (None,) + projection.RUNTIME_STATES
    seen = set()
    for record, launch, display, identity, claim in itertools.product(
            (True, False), (None, "finished", "refused", "uncertain"), displays, (True, False),
            (True, False)):
        status = None if display is None else journal(display, identity=identity)
        mapped = lr.map_status(record_present=record, terminal=None if launch is None else terminal(launch),
                               journal=status, claim_held=claim)
        assert mapped.state == expected_status(record, launch, display, identity, claim)
        assert mapped.state in {"queued", "running", "cancelling", "finished", "refused",
                                "uncertain", "unknown_attempt"}
        assert (mapped.launch is not None) == (mapped.state in contract.TERMINAL_STATUS_STATES
                                               and mapped.row == "laneexec_terminal")
        seen.add(mapped.row)
    assert seen == {"no_record", "laneexec_terminal", "journal_live", "claim_without_journal",
                    "no_journal_attempt", "journal_not_live"}


@pytest.mark.parametrize("display", ["finished (completed)", "finished (cancelled)", "refused",
                                     "unknown", "stale_unknown"])
def test_journal_terminal_alone_never_settles_status(display):
    mapped = lr.map_status(record_present=True, terminal=None, journal=journal(display),
                           claim_held=True)
    assert (mapped.state, mapped.launch) == ("uncertain", None)


def test_held_claim_with_no_journal_attempt_is_uncertain():
    mapped = lr.map_status(record_present=True, terminal=None, journal=None, claim_held=True)
    assert (mapped.state, mapped.row) == ("uncertain", "claim_without_journal")


def test_status_exit_classes_match_x_cli():
    for state in ("queued", "running", "cancelling"):
        response = contract.StatusResponse("s-1", "rsv-1", "req-1", state, None, "att-1",
                                           "/scratch/att-1", "/work/att-1/fs/repo", {})
        assert contract.launch_exit_class(response) == 0
    unknown = contract.StatusResponse("s-1", "rsv-1", "req-1", "unknown_attempt", None, None,
                                      None, None, {})
    assert contract.launch_exit_class(unknown) == 10


# -- L-S4 cancel table ------------------------------------------------------------------------

CANCEL_OUTCOMES = typing.get_args(patch_return.CancelOutcome)
ZERO_SIGNAL = {("unknown_attempt", True), ("owner_unverified", True), ("owner_unverified", False),
               ("owner_not_live", True), ("owner_not_live", False)}
EXPECTED_CANCEL = {
    "cancelled": ("cancelled", "cancelled"), "already_terminal": ("already_terminal", "already_terminal"),
    "cancel_pending": ("cancel_pending", "cancel_pending"),
    "unknown_attempt": ("unknown_attempt", "cancel_pending"),
    "owner_unverified": ("cancel_pending", "cancel_pending"),
    "owner_not_live": ("cancel_pending", "cancel_pending"),
}


def test_cancel_table_is_closed_over_the_landed_outcomes():
    assert set(CANCEL_OUTCOMES) == set(EXPECTED_CANCEL)
    assert set(lr.CANCEL_TABLE) == set(itertools.product(CANCEL_OUTCOMES, (True, False)))
    for outcome, claim in itertools.product(CANCEL_OUTCOMES, (True, False)):
        mapped = lr.map_cancel(outcome, record_present=True, claim_held=claim)
        assert mapped.state == EXPECTED_CANCEL[outcome][1 if claim else 0]
        if (outcome, claim) in ZERO_SIGNAL:
            assert mapped.state == "cancel_pending"
            assert mapped.state not in ("cancelled", "already_terminal")
            assert mapped.local_outcome == outcome
        else:
            assert mapped.local_outcome is None
        mapped_unrecorded = lr.map_cancel(outcome, record_present=False, claim_held=claim)
        assert mapped_unrecorded == lr.CancelMapping("unknown_attempt", None)


@pytest.mark.parametrize("outcome", [None, "", "cancelled ", "CANCELLED", "signalled", 0])
def test_cancel_outside_the_table_is_pending_never_success(outcome):
    for claim in (True, False):
        mapped = lr.map_cancel(outcome, record_present=True, claim_held=claim)
        assert mapped == lr.CancelMapping("cancel_pending", "unmapped")


def test_cancel_exit_classes_match_x_cli():
    classes = {}
    for outcome, claim in itertools.product(CANCEL_OUTCOMES, (True, False)):
        state = lr.map_cancel(outcome, record_present=True, claim_held=claim).state
        classes[state] = contract.launch_exit_class(
            contract.CancelResponse("c-1", "rsv-1", "req-1", state, {}))
    assert classes == {"cancelled": 0, "already_terminal": 0, "cancel_pending": 20,
                       "unknown_attempt": 10}


# -- review round 1 regressions (agent-harness#2118) ---------------------------------------

@pytest.mark.parametrize("kind", ["patch", "result"])
def test_withhold_leaves_no_payload_even_when_unlink_fails(state, kind, monkeypatch):
    (state["out"] / "result.json").write_bytes(b'{"ok": "' + SENTINEL + b'"}')
    item = attempt(state, store_proposal(state, patch_bytes()))

    def refuse_unlink(*args, **kwargs):
        raise PermissionError("unlink refused")

    monkeypatch.setattr(lr.os, "unlink", refuse_unlink)
    for predicate in (lambda data: True, lambda data: (_ for _ in ()).throw(RuntimeError())):
        outcome = lr.collect_return(item, kind, policy=POLICY, withhold=predicate,
                                    bound=bound())
        assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_withheld")
        assert returned_files(state) == []


class FakeClock:
    """A monotonic clock that advances one second per reading."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


@pytest.mark.parametrize("kind", ["patch", "result"])
def test_budget_expiring_during_return_never_publishes(state, kind, monkeypatch):
    (state["out"] / "result.json").write_bytes(b'{"ok": true}')
    item = attempt(state, store_proposal(state, patch_bytes()))
    # Count the bound checks of one full, successful return.
    calls = []
    lr.collect_return(item, kind, policy=POLICY, withhold=None,
                      bound=openshell_artifacts.Bound(time.monotonic() + 30,
                                                      lambda: calls.append(1) or False))
    for leftover in returned_files(state):
        os.unlink(state["return_dir"] / leftover)
    assert len(calls) >= 2
    # The budget is live at the start and expires at each later check, the last
    # one after the final write.
    for live in range(1, len(calls)):
        clock = FakeClock()
        monkeypatch.setattr(openshell_artifacts.time, "monotonic", clock)
        outcome = lr.collect_return(item, kind, policy=POLICY, withhold=None,
                                    bound=openshell_artifacts.Bound(live + 0.5, lambda: False))
        monkeypatch.undo()
        assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid"), live
        assert returned_files(state) == [], live


def test_budget_expiring_inside_the_withhold_predicate_never_publishes(state, monkeypatch):
    (state["out"] / "result.json").write_bytes(b'{"ok": true}')
    clock = FakeClock()
    monkeypatch.setattr(openshell_artifacts.time, "monotonic", clock)

    def slow(data):
        clock.now += 100.0
        return False

    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=slow,
                                bound=openshell_artifacts.Bound(50.0, lambda: False))
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert returned_files(state) == []


def test_expired_budget_with_failed_cleanup_publishes_nothing(state, monkeypatch):
    (state["out"] / "result.json").write_bytes(b'{"ok": true}')
    checks = []

    def expire_after_write():
        checks.append(1)
        return len(checks) >= 3  # live for the read and the pre-write check

    def refuse_unlink(*args, **kwargs):
        raise PermissionError("unlink refused")

    monkeypatch.setattr(lr.os, "unlink", refuse_unlink)
    outcome = lr.collect_return(attempt(state), "result", policy=POLICY, withhold=None,
                                bound=openshell_artifacts.Bound(time.monotonic() + 30,
                                                                expire_after_write))
    assert len(checks) == 3
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert outcome.status == "budget_exhausted_cleanup_pending"


class StableClock:
    """A monotonic clock that moves only when a test moves it."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.mark.parametrize("kind", ["patch", "result"])
def test_budget_expiring_after_the_directory_closes_never_publishes(state, kind, monkeypatch):
    (state["out"] / "result.json").write_bytes(b'{"ok": true}')
    item = attempt(state, store_proposal(state, patch_bytes()))
    clock = StableClock()
    real_close = os.close
    return_dir = state["return_dir"]

    def close_then_expire(fd):
        info = os.fstat(fd)
        real_close(fd)
        # Expire only when the return directory itself closes after a successful write.
        if (stat.S_ISDIR(info.st_mode) and return_dir.exists()
                and (info.st_dev, info.st_ino) == (return_dir.stat().st_dev,
                                                   return_dir.stat().st_ino)
                and any(return_dir.iterdir())):
            clock.now = 100.0

    monkeypatch.setattr(openshell_artifacts.time, "monotonic", clock)
    monkeypatch.setattr(lr.os, "close", close_then_expire)
    outcome = lr.collect_return(item, kind, policy=POLICY, withhold=None,
                                bound=openshell_artifacts.Bound(10.0, lambda: False))
    monkeypatch.undo()
    assert clock.now == 100.0
    assert (outcome.descriptor, outcome.code) == (None, "sandbox_launch_result_invalid")
    assert outcome.status == "budget_exhausted"
    assert returned_files(state) == []
