"""v13 LANEEXEC SL-0: the packaged placement launch protocol v1 and its strict codec.

Obligation C1 and the schema cases of C10 and C11 of the frozen wire artifact. Every
negative enters through the production codec (``decode_launch_request``,
``decode_launch_response`` or ``encode_launch_response``), never a schema call of the test's
own, and the packaged bytes are compared with the frozen planning artifact itself, so a
changed package copy cannot be hidden by updating an expectation here.
"""

from __future__ import annotations

import copy
from hashlib import sha256
from importlib import resources
import json
from pathlib import Path

import pytest

from phase_loop_runtime import launch_process_contract as contract
from phase_loop_runtime import placement_process_contract as placement

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = REPO / "plans/artifacts/v13-LANEEXEC-contract-v1.schema.json"
#: The roadmap and binding pin of the wire artifact (an input, never an output).
PINNED_SHA256 = "da311638f2c5b92df5b1f2a917665b62c06aa10f80040bfa2504dcd78f42442a"
#: The bytes before erratum LANEEXEC-v1-errata-1 (``x-errata.entries[0].previous_sha256``).
PREVIOUS_SHA256 = "bd0e6694e6df9e4ae0bc640c138645adf6b49e8f56aa3f5af7488107062676f3"
PLACECLI_ID = "https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json"
DIGEST = "sha256:" + "a" * 64
HEX = "b" * 64
COMMIT = "c" * 40


# -- example messages -----------------------------------------------------------------------

def reservation(**changes):
    body = {
        "schema": "placement.reservation.v1", "reservation_id": "rsv-1", "workload": "pi-runner",
        "target": {"name": "remote-1", "kind": "openshell", "rank": 0},
        "transport_id": "remote-openshell", "image_digest": DIGEST,
        "policy_vector": "full-remote-pi-runner", "policy_digest": DIGEST,
        "providers": ["anthropic"], "egress_sha256": DIGEST, "client": "agent-toolkit",
        "inventory": "agent-toolkit", "rank_policy": "agent_executor", "lease_id": "lease-1",
        "expires_at": "2026-11-09T18:00:00Z", "config_sha256": HEX,
        "bridge": {"kind": "forward_tcp_unix", "service_name": "pi-link",
                   "socket_path": "/run/user/1000/agent-harness-placement/agent-toolkit/rsv-1/s",
                   "directory_mode": "0700", "socket_mode": "0600", "lifetime": "reservation"},
    }
    body.update(changes)
    return body


def local_reservation(**changes):
    return reservation(target={"name": "local", "kind": "local", "rank": 1},
                       transport_id="local", policy_vector="minimal-without-app", lease_id=None,
                       bridge=None, **changes)


def harness_reservation(workload="implementation", **changes):
    return reservation(workload=workload, target={"name": "local", "kind": "local", "rank": 0},
                       transport_id="local", policy_vector="minimal-with-app", lease_id=None,
                       client="agent-harness", inventory="agent-harness",
                       rank_policy="seats_single_target", bridge=None, **changes)


def paths(run_id="run-1", remote=True):
    if remote:
        return {"run_id": run_id, "scratch_path": f"/work/{run_id}/scratch",
                "tree_path": f"/work/{run_id}/fs/srv/repo"}
    return {"run_id": run_id, "scratch_path": f"/state/laneexec/{run_id}/scratch",
            "tree_path": "/srv/repo"}


def snapshot(**changes):
    body = {"root": "/srv/repo", "mode": "git_overlay", "masks": [".env"],
            "mask_dirs": ["secrets"], "cwd": "."}
    body.update(changes)
    return body


def seed(**changes):
    body = {"manifest_sha256": HEX, "entries": 2, "total_bytes": 10}
    body.update(changes)
    return body


def prepare_request(**changes):
    body = {"schema": "placement.launch.prepare.request.v1", "request_id": "prep-1",
            "reservation": reservation(), "snapshot_root": "/srv/repo",
            "caller_context": {"run": "r-1", "attempt": 2, "dry": False, "note": None}}
    body.update(changes)
    return body


def remote_pi_request(**changes):
    body = {
        "schema": "placement.launch.request.v1", "request_id": "launch-1",
        "reservation": reservation(), "workload": "pi-runner", "image_digest": DIGEST,
        "policy_vector": "full-remote-pi-runner", "providers": ["anthropic"],
        "command": {"template_id": "pi-runner.openshell.v1", "template_sha256": HEX},
        "action": "execution", "result_kind": "none", "snapshot": snapshot(),
        "instructions": {"source": "none"}, "seed": seed(), "paths": paths(),
        "timeout_seconds": 600, "caller_context": {},
    }
    body.update(changes)
    return body


def local_pi_request(**changes):
    body = remote_pi_request(
        reservation=local_reservation(), policy_vector="minimal-without-app",
        command={"template_id": "pi-runner.local.v1", "template_sha256": HEX},
        paths=paths(remote=False))
    body.update(changes)
    return body


def implementation_request(**changes):
    body = remote_pi_request(
        reservation=harness_reservation(), workload="implementation",
        policy_vector="minimal-with-app",
        command={"template_id": "implementation.local.v1", "template_sha256": HEX},
        result_kind="patch", snapshot=snapshot(mode="git"), seed=None, paths=None,
        instructions={"source": "inline", "base64": "aGVsbG8="})
    body.update(changes)
    return body


def review_request(workload="leg", **changes):
    body = implementation_request(
        reservation=harness_reservation(workload), workload=workload, action="review",
        result_kind="result", instructions={"source": "snapshot", "path": "docs/brief.md"})
    body.update(changes)
    return body


def status_request(**changes):
    body = {"schema": "placement.launch.status.request.v1", "request_id": "st-1",
            "reservation_id": "rsv-1", "launch_request_id": "launch-1", "caller_context": {}}
    body.update(changes)
    return body


def cancel_request(**changes):
    body = {"schema": "placement.launch.cancel.request.v1", "request_id": "cn-1",
            "reservation_id": "rsv-1", "launch_request_id": "launch-1", "deadline_ms": 30000,
            "caller_context": {}}
    body.update(changes)
    return body


def prepare_response(**changes):
    body = {"schema": "placement.launch.prepare.response.v1", "request_id": "prep-1",
            "reservation_id": "rsv-1", "state": "prepared", "code": None, "paths": paths(),
            "caller_context": {}}
    body.update(changes)
    return body


def snapshot_evidence(**changes):
    body = {"mode": "git_overlay", "content_sha256": HEX, "base_commit": COMMIT,
            "input_commit": COMMIT, "overlay_sha256": HEX, "inventory_sha256": HEX,
            "masks_sha256": HEX,
            "counts": {"tracked": 3, "untracked": 1, "ignored": 0, "omitted": 0, "masked": 1,
                       "special": 0},
            "byte_total": 100}
    body.update(changes)
    return body


def evidence(**changes):
    body = {"snapshot": snapshot_evidence(), "launch_digest": HEX, "template_sha256": HEX,
            "image_digest": DIGEST, "policy_digest": DIGEST, "egress_sha256": DIGEST,
            "transport_id": "remote-openshell", "caps_sha256": None, "bridge_attached": True,
            "stdout_sha256": HEX, "stderr_sha256": HEX, "exit_status": 0, "duration_ms": 1200,
            "renewals": 1}
    body.update(changes)
    return body


def return_descriptor(**changes):
    body = {"kind": "patch", "format": "worker_proposal_bytes", "path": "/state/return/p",
            "sha256": HEX, "byte_length": 42, "directory_mode": "0700", "file_mode": "0600",
            "base_commit": COMMIT}
    body.update(changes)
    return body


def finished_response(**changes):
    p = paths()
    body = {"schema": "placement.launch.response.v1", "request_id": "launch-1",
            "reservation_id": "rsv-1", "attempt_id": p["run_id"], "state": "finished",
            "code": None, "snapshot_reason": None, "seed_reason": None,
            "admission_diagnostic": None,
            "termination": {"reason": "completed", "signal": None, "by": "worker"},
            "worker_invocations": 1, "envelope_digest": HEX, "scratch_path": p["scratch_path"],
            "tree_path": p["tree_path"], "return": None, "evidence": evidence(),
            "caller_context": {}}
    body.update(changes)
    return body


def refused_response(code="sandbox_launch_input_mismatch", **changes):
    body = finished_response(attempt_id=None, state="refused", code=code, termination=None,
                             worker_invocations=0, envelope_digest=None, scratch_path=None,
                             tree_path=None, evidence=None)
    body.update(changes)
    return body


def uncertain_response(**changes):
    body = finished_response(state="uncertain", code="sandbox_placement_lost_after_launch",
                             termination=None)
    body.update(changes)
    return body


def status_response(state="finished", launch=None, **changes):
    if launch is None and state in contract.TERMINAL_STATUS_STATES:
        launch = {"finished": finished_response, "refused": refused_response,
                  "uncertain": uncertain_response}[state]()
    if launch is not None:
        top = {"run_id": launch["attempt_id"], "scratch_path": launch["scratch_path"],
               "tree_path": launch["tree_path"]}
    elif state == "unknown_attempt":
        top = {"run_id": None, "scratch_path": None, "tree_path": None}
    else:
        top = paths()
    body = {"schema": "placement.launch.status.response.v1", "request_id": "st-1",
            "reservation_id": "rsv-1", "launch_request_id": "launch-1", "state": state,
            "launch": launch, **top, "caller_context": {}}
    body.update(changes)
    return body


def cancel_response(**changes):
    body = {"schema": "placement.launch.cancel.response.v1", "request_id": "cn-1",
            "reservation_id": "rsv-1", "launch_request_id": "launch-1", "state": "cancelled",
            "caller_context": {}}
    body.update(changes)
    return body


SEED_LIMITS = {"max_entries": 4096, "entry_max_bytes": 16777216, "max_bytes": 67108864,
               "manifest_max_bytes": 1048576}


def version_response(**changes):
    body = {"schema": "placement.launch.version.response.v1", "client": "agent-toolkit",
            "protocol_schema_sha256": PINNED_SHA256,
            "placement_protocol_schema_sha256": placement.protocol_schema_sha256(),
            "config_sha256": HEX, "seat_caps_sha256": HEX,
            "local_pi_runner_launcher": "toolkit_interim", "local_link_root": "/opt/links",
            "seed_root": "/state/seed", "seed_limits": dict(SEED_LIMITS),
            "templates": [{"template_id": "pi-runner.local.v1", "template_sha256": HEX,
                           "workload": "pi-runner"}]}
    body.update(changes)
    return body


def raw(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def line(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


def refused(verb: str, data: bytes) -> str:
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_launch_request(verb, data)
    assert str(caught.value) in placement.PROTOCOL_DIAGNOSTICS
    return caught.value.code


def response_refused(verb: str, value) -> None:
    with pytest.raises(contract.ProtocolError):
        contract.decode_launch_response(verb, line(value))


def at(value, path: str, new):
    """A deep copy of ``value`` with the member at dotted ``path`` replaced (or removed)."""
    result = copy.deepcopy(value)
    node = result
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = keys[-1]
    if new is _REMOVE:
        del node[last]
    elif isinstance(node, list):
        node[int(last)] = new
    else:
        node[last] = new
    return result


_REMOVE = object()

REQUESTS = {
    "prepare": prepare_request, "remote-pi": remote_pi_request, "local-pi": local_pi_request,
    "implementation": implementation_request, "leg": lambda: review_request("leg"),
    "qualification": lambda: review_request("qualification"), "status": status_request,
    "cancel": cancel_request,
}
REQUEST_VERB = {"prepare": "prepare", "remote-pi": "launch", "local-pi": "launch",
                "implementation": "launch", "leg": "launch", "qualification": "launch",
                "status": "status", "cancel": "cancel"}


# -- the packaged bytes ---------------------------------------------------------------------

def test_the_packaged_schema_is_read_through_importlib_resources():
    packaged = resources.files("phase_loop_runtime").joinpath(
        "contracts/placement/launch-v1.schema.json").read_bytes()
    assert packaged == contract.schema_bytes()
    assert contract.protocol_schema_sha256() == sha256(packaged).hexdigest()


@pytest.mark.skipif(not ARTIFACT.is_file(), reason="planning artifact absent in standalone clean-room")
def test_the_packaged_bytes_are_the_frozen_artifact_at_its_pin():
    frozen = ARTIFACT.read_bytes()
    # Equal to the artifact itself, and the artifact is at its roadmap pin: changing the
    # package copy and an expectation here together still fails one of the two.
    assert contract.schema_bytes() == frozen
    assert sha256(frozen).hexdigest() == PINNED_SHA256
    assert contract.protocol_schema_sha256() == PINNED_SHA256


def test_the_wire_identity_is_the_erratum_one_bytes():
    assert contract.protocol_schema_sha256() == PINNED_SHA256
    assert contract.protocol_schema_sha256() != PREVIOUS_SHA256
    document = json.loads(contract.schema_bytes())
    assert document["x-errata"]["entries"][0]["id"] == "LANEEXEC-v1-errata-1"
    assert document["x-errata"]["entries"][0]["previous_sha256"] == PREVIOUS_SHA256


def test_the_in_process_api_names_the_codec_entry_points():
    signatures = json.loads(contract.schema_bytes())["x-in-process-api"]["signatures"]
    assert "decode_launch_request(verb: str, raw: bytes) -> LaunchProcessRequest" in signatures
    assert "encode_launch_response(message: LaunchProcessResponse) -> bytes" in signatures
    assert callable(contract.decode_launch_request)
    assert callable(contract.encode_launch_response)


def test_the_verbs_and_exit_classes_are_the_frozen_cli():
    cli = json.loads(contract.schema_bytes())["x-cli"]
    assert cli["argv"][-1] == "<" + "|".join(contract.VERBS) + ">"
    assert set(cli["exit_codes"]) == {"0", "10", "20", "70"}
    assert "schema-invalid" in cli["exit_codes"][str(contract.PROTOCOL_EXIT)]


# -- PLACECLI Reservation reuse by $id ------------------------------------------------------

def test_reservation_is_the_placecli_definition_by_id():
    document = json.loads(contract.schema_bytes())
    for message in ("PrepareRequest", "LaunchRequest"):
        assert document["$defs"][message]["properties"]["reservation"] == {
            "$ref": PLACECLI_ID + "#/$defs/Reservation"}
    assert "Reservation" not in document["$defs"]
    assert json.loads(placement.schema_bytes())["$id"] == PLACECLI_ID
    pin = document["x-contract-pins"]["placement_process_v1"]
    assert placement.protocol_schema_sha256() == pin["sha256"]


def test_a_placecli_reservation_rule_is_enforced_inside_launch_messages():
    # PLACECLI's own conditionals (pi-runner belongs to agent-toolkit; a local pi-runner
    # reservation has no bridge) apply only if the $ref resolves to the packaged process-v1.
    for bad in (reservation(client="agent-harness"), at(local_reservation(), "bridge", reservation()["bridge"]),
                at(reservation(), "target.kind", "elsewhere"), reservation(extra=1)):
        assert refused("prepare", raw(prepare_request(reservation=bad))) == "schema_invalid"
        assert refused("launch", raw(remote_pi_request(reservation=bad))) == "schema_invalid"


def test_the_decoded_reservation_is_the_placecli_record_with_its_echo():
    request = contract.decode_launch_request("launch", raw(remote_pi_request()))
    assert isinstance(request.reservation, placement.Reservation)
    assert request.reservation.to_json() == reservation()
    assert dict(request.reservation_json) == reservation()


def test_an_unresolvable_reference_fails_closed(monkeypatch):
    import referencing
    contract._validator.cache_clear()
    monkeypatch.setattr(contract, "_registry", lambda: referencing.Registry())
    try:
        assert refused("launch", raw(remote_pi_request())) == "schema_invalid"
    finally:
        monkeypatch.undo()
        contract._validator.cache_clear()
    assert isinstance(contract.decode_launch_request("launch", raw(remote_pi_request())),
                      contract.LaunchRequest)


# -- every message family valid ------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_every_request_family_decodes_and_round_trips(name):
    body = REQUESTS[name]()
    record = contract.decode_launch_request(REQUEST_VERB[name], raw(body))
    assert record.to_json() == body


def test_the_remote_and_local_pi_requests_validate():
    remote = contract.decode_launch_request("launch", raw(remote_pi_request()))
    local = contract.decode_launch_request("launch", raw(local_pi_request()))
    assert (remote.reservation.target.kind, remote.policy_vector, remote.result_kind) == (
        "openshell", "full-remote-pi-runner", "none")
    assert (local.reservation.target.kind, local.policy_vector, local.result_kind) == (
        "local", "minimal-without-app", "none")


def test_both_crossed_pi_policy_target_pairs_are_schema_valid():
    # The binding refusal (sandbox_launch_input_mismatch) belongs to C2, not the codec.
    crossed_remote = remote_pi_request(policy_vector="minimal-without-app")
    crossed_local = local_pi_request(policy_vector="full-remote-pi-runner")
    for body in (crossed_remote, crossed_local):
        assert contract.decode_launch_request("launch", raw(body)).to_json() == body


RESPONSES = {
    "prepare-prepared": ("prepare", prepare_response),
    "prepare-refused": ("prepare", lambda: prepare_response(
        state="refused", code="sandbox_launch_reservation_unknown", paths=None)),
    "prepare-timeout": ("prepare", lambda: prepare_response(
        state="timeout", code="sandbox_placement_end_reached", paths=None)),
    "launch-finished": ("launch", finished_response),
    "launch-finished-patch": ("launch", lambda: finished_response() | {
        "return": return_descriptor()}),
    "launch-finished-result": ("launch", lambda: finished_response() | {"return": return_descriptor(
        kind="result", format="json_object", byte_length=1048576, base_commit=None)}),
    "launch-refused": ("launch", refused_response),
    "launch-refused-snapshot": ("launch", lambda: refused_response(
        "sandbox_launch_snapshot_refused", snapshot_reason="dirty_source")),
    "launch-refused-seed": ("launch", lambda: refused_response(
        "sandbox_launch_seed_refused", seed_reason="scratch_unprovisioned")),
    "launch-refused-admission": ("launch", lambda: refused_response(
        "sandbox_launch_admission_refused", admission_diagnostic="route_not_qualified")),
    "launch-uncertain": ("launch", uncertain_response),
    "status-queued": ("status", lambda: status_response("queued")),
    "status-running": ("status", lambda: status_response("running")),
    "status-cancelling": ("status", lambda: status_response("cancelling")),
    "status-finished": ("status", lambda: status_response("finished")),
    "status-refused": ("status", lambda: status_response("refused")),
    "status-uncertain": ("status", lambda: status_response("uncertain")),
    "status-unknown": ("status", lambda: status_response("unknown_attempt")),
    "cancel-cancelled": ("cancel", cancel_response),
    "cancel-terminal": ("cancel", lambda: cancel_response(state="already_terminal")),
    "cancel-pending": ("cancel", lambda: cancel_response(state="cancel_pending")),
    "cancel-unknown": ("cancel", lambda: cancel_response(state="unknown_attempt")),
    "version": ("version", version_response),
    "version-no-seed": ("version", lambda: version_response(seed_root=None, seed_limits=None,
                                                            local_link_root=None, templates=[])),
}
EXIT_CLASS = {
    "prepare-prepared": 0, "prepare-refused": 10, "prepare-timeout": 20,
    "launch-finished": 0, "launch-finished-patch": 0, "launch-finished-result": 0,
    "launch-refused": 10, "launch-refused-snapshot": 10, "launch-refused-seed": 10,
    "launch-refused-admission": 10, "launch-uncertain": 20,
    "status-queued": 0, "status-running": 0, "status-cancelling": 0, "status-finished": 0,
    "status-refused": 0, "status-uncertain": 0, "status-unknown": 10,
    "cancel-cancelled": 0, "cancel-terminal": 0, "cancel-pending": 20, "cancel-unknown": 10,
    "version": 0, "version-no-seed": 0,
}


@pytest.mark.parametrize("name", sorted(RESPONSES))
def test_every_response_family_round_trips_through_the_codec(name):
    verb, build = RESPONSES[name]
    body = build()
    record = contract.decode_launch_response(verb, line(body))
    encoded = contract.encode_launch_response(record)
    assert encoded == line(body)
    assert encoded.endswith(b"\n") and encoded.count(b"\n") == 1
    assert contract.launch_exit_class(record) == EXIT_CLASS[name]


def test_the_message_families_cover_the_schema_one_of():
    document = json.loads(contract.schema_bytes())
    families = {entry["$ref"].rsplit("/", 1)[1] for entry in document["oneOf"]}
    assert families == {"PrepareRequest", "PrepareResponse", "LaunchRequest", "LaunchResponse",
                        "StatusRequest", "StatusResponse", "CancelRequest", "CancelResponse",
                        "LaunchVersionResponse"}


@pytest.mark.parametrize("code", sorted(json.loads(contract.schema_bytes())["$defs"]["LaunchCode"]["enum"]))
def test_every_launch_code_is_accepted_on_a_refused_launch(code):
    reasons = {"sandbox_launch_snapshot_refused": {"snapshot_reason": "too_large"},
               "sandbox_launch_seed_refused": {"seed_reason": "symlink"},
               "sandbox_launch_admission_refused": {"admission_diagnostic": "codec_unavailable"}}
    body = refused_response(code, **reasons.get(code, {}))
    assert contract.decode_launch_response("launch", line(body)).code == code


def test_a_placement_code_is_a_launch_result_code():
    body = refused_response("sandbox_placement_capability_unmet")
    assert contract.decode_launch_response("launch", line(body)).code == (
        "sandbox_placement_capability_unmet")


# -- every closed enum, path-entered --------------------------------------------------------

ENUM_REQUEST_CASES = [
    ("remote-pi", "workload", "pi"),
    ("remote-pi", "policy_vector", "full"),
    ("remote-pi", "action", "exec"),
    ("remote-pi", "result_kind", "diff"),
    ("remote-pi", "snapshot.mode", "tarball"),
    ("remote-pi", "instructions.source", "stdin"),
    ("remote-pi", "reservation.workload", "pi"),
    ("remote-pi", "reservation.policy_vector", "open"),
    ("remote-pi", "reservation.client", "someone"),
    ("remote-pi", "reservation.rank_policy", "random"),
    ("prepare", "reservation.target.kind", "cloud"),
]


@pytest.mark.parametrize("name,path,bad", ENUM_REQUEST_CASES)
def test_every_closed_request_enum_refuses_an_unknown_value(name, path, bad):
    assert refused(REQUEST_VERB[name], raw(at(REQUESTS[name](), path, bad))) == "schema_invalid"


ENUM_RESPONSE_CASES = [
    ("prepare-prepared", "state", "ready"),
    ("prepare-refused", "code", "sandbox_launch_unknown_code"),
    ("launch-finished", "state", "done"),
    ("launch-refused", "code", "sandbox_launch_unknown_code"),
    ("launch-refused-snapshot", "snapshot_reason", "messy"),
    ("launch-refused-seed", "seed_reason", "messy"),
    ("launch-refused-admission", "admission_diagnostic", "messy"),
    ("launch-finished", "termination.reason", "exploded"),
    ("launch-finished", "termination.by", "someone"),
    ("launch-finished-patch", "return.kind", "tarball"),
    ("launch-finished-patch", "return.format", "zip"),
    ("launch-finished-patch", "return.directory_mode", "0755"),
    ("launch-finished-patch", "return.file_mode", "0644"),
    ("launch-finished", "evidence.snapshot.mode", "tarball"),
    ("status-running", "state", "paused"),
    ("cancel-cancelled", "state", "gone"),
    ("version", "client", "someone"),
    ("version", "local_pi_runner_launcher", "bwrap"),
    ("version", "templates.0.workload", "pi"),
]


@pytest.mark.parametrize("name,path,bad", ENUM_RESPONSE_CASES)
def test_every_closed_response_enum_refuses_an_unknown_value(name, path, bad):
    verb, build = RESPONSES[name]
    response_refused(verb, at(build(), path, bad))


@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_requests_refuse_unknown_and_missing_members(name):
    verb = REQUEST_VERB[name]
    body = REQUESTS[name]()
    assert refused(verb, raw({**body, "extra": 1})) == "schema_invalid"
    for member in body:
        assert refused(verb, raw(at(body, member, _REMOVE))) == "schema_invalid"
    assert refused(verb, raw({**body, "schema": body["schema"].replace("v1", "v2")})) == (
        "schema_invalid")


# -- conditional paths ----------------------------------------------------------------------

CONDITIONAL_REQUEST_CASES = [
    # pi-runner: execution, result_kind none, a pi policy vector, prepared paths required.
    ("remote-pi", "policy_vector", "minimal-with-app"),
    ("remote-pi", "action", "review"),
    ("remote-pi", "result_kind", "patch"),
    ("remote-pi", "result_kind", "result"),
    ("remote-pi", "paths", None),
    ("local-pi", "result_kind", "patch"),
    ("local-pi", "paths", None),
    # implementation: execution, patch, no seed.
    ("implementation", "action", "review"),
    ("implementation", "result_kind", "none"),
    ("implementation", "result_kind", "result"),
    ("implementation", "seed", seed()),
    # leg and qualification: review, result, no seed.
    ("leg", "action", "execution"),
    ("leg", "result_kind", "patch"),
    ("leg", "seed", seed()),
    ("qualification", "action", "execution"),
    ("qualification", "result_kind", "none"),
    ("qualification", "seed", seed()),
]


@pytest.mark.parametrize("name,path,bad", CONDITIONAL_REQUEST_CASES)
def test_every_launch_request_conditional_refuses_when_entered(name, path, bad):
    assert refused("launch", raw(at(REQUESTS[name](), path, bad))) == "schema_invalid"


def test_patch_with_pi_runner_is_refused():
    for body in (remote_pi_request(result_kind="patch", seed=None),
                 local_pi_request(result_kind="patch", seed=None)):
        assert refused("launch", raw(body)) == "schema_invalid"


def test_a_non_pi_launch_may_carry_prepared_paths_or_null():
    for body in (implementation_request(paths=paths(remote=False)), implementation_request()):
        assert contract.decode_launch_request("launch", raw(body)).to_json() == body


CONDITIONAL_RESPONSE_CASES = [
    # PrepareResponse
    ("prepare-prepared", "code", "sandbox_launch_refused"),
    ("prepare-prepared", "paths", None),
    ("prepare-refused", "code", "sandbox_launch_image_refused"),
    ("prepare-refused", "code", None),
    ("prepare-refused", "paths", paths()),
    ("prepare-timeout", "code", "sandbox_launch_refused"),
    ("prepare-timeout", "paths", paths()),
    # LaunchResponse refused
    ("launch-refused", "code", None),
    ("launch-refused", "termination", {"reason": "completed", "signal": None, "by": "worker"}),
    ("launch-refused", "worker_invocations", 1),
    ("launch-refused", "return", return_descriptor()),
    ("launch-refused", "scratch_path", "/work/run-1/scratch"),
    ("launch-refused", "tree_path", "/work/run-1/fs/srv/repo"),
    # LaunchResponse finished
    ("launch-finished", "attempt_id", None),
    ("launch-finished", "termination", None),
    ("launch-finished", "envelope_digest", None),
    ("launch-finished", "evidence", None),
    ("launch-finished", "scratch_path", None),
    ("launch-finished", "tree_path", None),
    ("launch-finished", "worker_invocations", 2),
    # LaunchResponse uncertain
    ("launch-uncertain", "code", "sandbox_launch_input_mismatch"),
    ("launch-uncertain", "return", return_descriptor()),
    # reason members follow their code
    ("launch-refused-snapshot", "snapshot_reason", None),
    ("launch-refused", "snapshot_reason", "dirty_source"),
    ("launch-refused-seed", "seed_reason", None),
    ("launch-refused", "seed_reason", "symlink"),
    ("launch-refused-admission", "admission_diagnostic", None),
    ("launch-refused", "admission_diagnostic", "route_not_qualified"),
    ("launch-finished", "snapshot_reason", "dirty_source"),
    ("launch-finished", "admission_diagnostic", "route_not_qualified"),
    # ReturnDescriptor
    ("launch-finished-patch", "return.format", "json_object"),
    ("launch-finished-patch", "return.base_commit", None),
    ("launch-finished-result", "return.format", "worker_proposal_bytes"),
    ("launch-finished-result", "return.byte_length", 1048577),
    ("launch-finished-result", "return.base_commit", COMMIT),
    # SnapshotEvidence overlay digest follows the mode
    ("launch-finished", "evidence.snapshot.overlay_sha256", None),
    ("launch-finished", "evidence.snapshot.mode", "git"),
    # StatusResponse
    ("status-finished", "launch", None),
    ("status-refused", "launch", None),
    ("status-uncertain", "launch", None),
    ("status-running", "launch", finished_response()),
    ("status-queued", "run_id", None),
    ("status-running", "scratch_path", None),
    ("status-cancelling", "tree_path", None),
    ("status-unknown", "run_id", "run-1"),
    ("status-unknown", "scratch_path", "/work/run-1/scratch"),
    ("status-unknown", "tree_path", "/work/run-1/fs/srv/repo"),
    ("status-unknown", "launch", finished_response()),
    # LaunchVersionResponse seed_root and seed_limits go together
    ("version", "seed_limits", None),
    ("version-no-seed", "seed_limits", dict(SEED_LIMITS)),
]


@pytest.mark.parametrize("name,path,bad", CONDITIONAL_RESPONSE_CASES)
def test_every_response_conditional_refuses_when_entered(name, path, bad):
    verb, build = RESPONSES[name]
    body = at(build(), path, bad)
    response_refused(verb, body)


@pytest.mark.parametrize("name,path,bad", CONDITIONAL_RESPONSE_CASES[:22])
def test_the_encoder_refuses_a_record_that_breaks_a_conditional(name, path, bad):
    verb, build = RESPONSES[name]
    record = contract.decode_launch_response(verb, line(build()))
    member = {"return": "return_"}.get(path, path)
    if "." in path:
        pytest.skip("nested members are covered by the decoder cases")
    import dataclasses
    current = getattr(record, member)
    replacement = bad
    if isinstance(bad, dict):
        replacement = {"termination": contract.Termination, "return": contract.ReturnDescriptor,
                       "paths": contract.PreparedPaths}[path].from_json(bad)
    if replacement == current:
        pytest.skip("no change")
    with pytest.raises(contract.ProtocolError) as caught:
        contract.encode_launch_response(dataclasses.replace(record, **{member: replacement}))
    assert caught.value.code == "response_invalid"


# -- C11: the status echo -------------------------------------------------------------------

def test_a_finished_status_with_a_null_top_level_value_fails_the_schema():
    for member in ("run_id", "scratch_path", "tree_path"):
        response_refused("status", at(status_response("finished"), member, None))


@pytest.mark.parametrize("state", sorted(contract.TERMINAL_STATUS_STATES))
@pytest.mark.parametrize("member", ["run_id", "scratch_path", "tree_path"])
def test_the_codec_refuses_a_terminal_status_whose_echo_differs_from_the_launch(state, member):
    good = status_response(state)
    changed = {"run_id": "run-2", "scratch_path": "/work/run-2/scratch",
               "tree_path": "/work/run-1/fs/srv/repo/sub"}[member]
    body = at(good, member, changed)
    # Schema-valid on its own (JSON Schema cannot compare two members) ...
    assert contract.validate_launch_message("StatusResponse", body)
    # ... and refused by the strict codec in both directions.
    response_refused("status", body)
    import dataclasses
    record = contract.decode_launch_response("status", line(good))
    with pytest.raises(contract.ProtocolError) as caught:
        contract.encode_launch_response(dataclasses.replace(record, **{member: changed}))
    assert caught.value.code == "response_invalid"


def test_the_status_echo_equals_the_launch_attempt_and_paths():
    record = contract.decode_launch_response("status", line(status_response("finished")))
    assert record.run_id == record.launch.attempt_id
    assert (record.scratch_path, record.tree_path) == (record.launch.scratch_path,
                                                       record.launch.tree_path)


def test_prepare_request_and_response_carry_the_prepared_paths():
    request = contract.decode_launch_request("prepare", raw(prepare_request()))
    assert request.snapshot_root == "/srv/repo"
    response = contract.decode_launch_response("prepare", line(prepare_response()))
    assert response.paths == contract.PreparedPaths("run-1", "/work/run-1/scratch",
                                                    "/work/run-1/fs/srv/repo")
    assert refused("prepare", raw(prepare_request(snapshot_root="srv/repo"))) == "schema_invalid"
    assert refused("prepare", raw(prepare_request(paths=paths()))) == "schema_invalid"


# -- C10: the schema cases of seed and scratch ---------------------------------------------

def test_a_seed_for_a_workload_other_than_pi_runner_is_schema_invalid():
    for body in (implementation_request(seed=seed()), review_request("leg", seed=seed()),
                 review_request("qualification", seed=seed())):
        assert refused("launch", raw(body)) == "schema_invalid"


def test_seed_declaration_ceilings():
    assert refused("launch", raw(remote_pi_request(seed=seed(entries=4097)))) == "schema_invalid"
    assert refused("launch", raw(remote_pi_request(seed=seed(entries=0)))) == "schema_invalid"
    assert refused("launch", raw(remote_pi_request(seed=seed(total_bytes=67108865)))) == (
        "schema_invalid")
    assert refused("launch", raw(remote_pi_request(seed=seed(manifest_sha256="A" * 64)))) == (
        "schema_invalid")
    at_cap = remote_pi_request(seed=seed(entries=4096, total_bytes=67108864))
    assert contract.decode_launch_request("launch", raw(at_cap)).seed.entries == 4096
    assert contract.decode_launch_request("launch", raw(remote_pi_request(seed=None))).seed is None


def test_a_launch_request_with_a_scratch_member_is_schema_invalid():
    assert refused("launch", raw({**remote_pi_request(), "scratch": "/work/run-1/scratch"})) == (
        "schema_invalid")
    assert refused("launch", raw(at(remote_pi_request(), "paths.scratch", "/x"))) == "schema_invalid"


def _manifest(*relpaths):
    return {"schema": "laneexec.seed.manifest.v1", "request_id": "launch-1",
            "entries": [{"relpath": r, "sha256": HEX, "size": 1} for r in relpaths]}


def test_seed_manifest_relpath_shape():
    valid = "/".join(["a" * 255, "b" * 255, "c" * 255, "d" * 254, "e"])
    assert len(valid) == 1024
    assert contract.validate_launch_message("SeedManifest", _manifest(valid))
    record = contract.SeedManifest.from_json(_manifest(valid, "x/y"))
    assert record.to_json() == _manifest(valid, "x/y")
    for bad in (valid + "f", "a" * 256, "/abs", "./a", "a/../b", "a//b", "a/", "..", ".", ""):
        assert not contract.validate_launch_message("SeedManifest", _manifest(bad)), bad
    assert not contract.validate_launch_message(
        "SeedManifest", {**_manifest("a"), "request_id": "bad id"})
    assert not contract.validate_launch_message("SeedManifest", {**_manifest("a"), "entries": []})
    too_big = _manifest("a")
    too_big["entries"][0]["size"] = 16777217
    assert not contract.validate_launch_message("SeedManifest", too_big)


def test_seed_entry_executable_is_optional_and_preserved():
    entry = {"relpath": "bin/tool", "sha256": HEX, "size": 3, "executable": True}
    assert contract.SeedEntry.from_json(entry).to_json() == entry
    plain = {"relpath": "a", "sha256": HEX, "size": 3}
    assert contract.SeedEntry.from_json(plain).to_json() == plain
    assert not contract.validate_launch_message("SeedEntry", {**plain, "executable": "yes"})


def test_unknown_definitions_never_validate():
    assert not contract.validate_launch_message("Nope", {})
    assert not contract.validate_launch_message(None, {})  # type: ignore[arg-type]


# -- strictness rules, 64 KiB bound and exit 70 ---------------------------------------------

def test_the_64_kib_bound():
    body = remote_pi_request()
    filler = 65536 - (len(raw(body)) - 1 + len(b', "pad": "') + 2)
    # The schema has no "pad" member, so a body at the bound is schema_invalid, not too large.
    at_bound = raw(body)[:-1] + b', "pad": "' + b"x" * filler + b'"}'
    assert len(at_bound) == 65536
    assert refused("launch", at_bound) == "schema_invalid"
    over = raw(body)[:-1] + b', "pad": "' + b"x" * (filler + 1) + b'"}'
    assert len(over) == 65537
    assert refused("launch", over) == "input_too_large"
    padded = raw(body) + b" " * (65536 - len(raw(body)))
    assert contract.decode_launch_request("launch", padded).request_id == "launch-1"
    assert refused("launch", padded + b" ") == "input_too_large"


@pytest.mark.parametrize("data,code", [
    (b'{"schema": "a", "schema": "b"}', "input_duplicate_key"),
    (b'{"x": NaN}', "input_non_finite_number"),
    (b'{"x": Infinity}', "input_non_finite_number"),
    (b'{"x": 1e999}', "input_non_finite_number"),
    (b'{"x": 9007199254740993}', "input_unsafe_number"),
    (b'{} {}', "input_trailing_data"),
    (b'{}\n{}', "input_trailing_data"),
    (b'\xff{}', "input_not_utf8"),
    (b'\xef\xbb\xbf{}', "input_not_utf8"),
    (b'{"x": "\\ud800"}', "input_not_utf8"),
    (b'[]', "input_not_object"),
    (b'"launch"', "input_not_object"),
    (b'', "input_invalid_json"),
    (b'{', "input_invalid_json"),
])
def test_the_placecli_strictness_rules_apply(data, code):
    for verb in contract.REQUEST_VERBS:
        assert refused(verb, data) == code


def test_a_duplicate_key_deep_in_a_valid_request_is_refused():
    data = raw(remote_pi_request()).replace(b'"cwd": "."', b'"cwd": ".", "cwd": "."')
    assert refused("launch", data) == "input_duplicate_key"


def test_input_must_be_bytes_and_the_verb_must_be_known():
    assert refused("launch", remote_pi_request()) == "input_not_bytes"  # type: ignore[arg-type]
    for verb in ("reserve", "release", "reap", "version", "LAUNCH", "", None):
        assert refused(verb, raw(remote_pi_request())) == "verb_unknown"  # type: ignore[arg-type]
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_launch_response("reserve", line(prepare_response()))
    assert caught.value.code == "verb_unknown"


def test_a_request_body_for_another_verb_is_schema_invalid():
    assert refused("launch", raw(prepare_request())) == "schema_invalid"
    assert refused("prepare", raw(remote_pi_request())) == "schema_invalid"
    assert refused("status", raw(cancel_request())) == "schema_invalid"
    assert refused("cancel", raw(status_request())) == "schema_invalid"


def test_strict_integers_and_bounds():
    assert refused("launch", raw(remote_pi_request(timeout_seconds=True))) == "schema_invalid"
    assert refused("launch", raw(remote_pi_request(timeout_seconds=1.0))) == "schema_invalid"
    assert refused("launch", raw(remote_pi_request(timeout_seconds=0))) == "schema_invalid"
    assert refused("launch", raw(remote_pi_request(timeout_seconds=3601))) == "schema_invalid"
    assert refused("cancel", raw(cancel_request(deadline_ms=30001))) == "schema_invalid"
    assert refused("prepare", raw(prepare_request(
        reservation=reservation(expires_at="tomorrow")))) == "schema_invalid"


def test_schema_invalid_input_is_exit_70_with_stdout_absent(capsys):
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_launch_request("launch", raw(remote_pi_request(workload="pi")))
    assert isinstance(caught.value, placement.ProtocolError)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert contract.PROTOCOL_EXIT == 70
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_diagnostics_never_carry_input_values():
    secret = "SENTINEL-credential-value"
    for body in (remote_pi_request(caller_context={"k": secret * 30}),
                 remote_pi_request(workload=secret)):
        with pytest.raises(contract.ProtocolError) as caught:
            contract.decode_launch_request("launch", raw(body))
        assert secret not in str(caught.value) and secret not in repr(caught.value.args)


def test_decoded_records_are_immutable():
    record = contract.decode_launch_request("launch", raw(remote_pi_request()))
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.workload = "leg"  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.caller_context["x"] = 1  # type: ignore[index]
    assert isinstance(record.providers, tuple) and isinstance(record.snapshot.masks, tuple)


# -- the encoder ----------------------------------------------------------------------------

def test_the_encoder_refuses_requests_and_foreign_objects():
    request = contract.decode_launch_request("status", raw(status_request()))
    for message in (request, object(), placement.VersionResponse(
            "agent-toolkit", HEX, HEX, placement.LocalHeadroomConfig.from_json({
                "memory_available_bytes_minimum_floor": 1,
                "memory_available_total_ram_fraction_minimum": 0.1,
                "load_per_cpu_percent_maximum_exclusive": 70,
                "io_pressure_full_avg10_percent_maximum_exclusive": 10,
                "memory_pressure_some_avg10_percent_maximum_exclusive": 10,
                "live_sandboxes_maximum_exclusive": 4, "observation_age_seconds_maximum": 5}))):
        with pytest.raises(contract.ProtocolError) as caught:
            contract.encode_launch_response(message)  # type: ignore[arg-type]
        assert caught.value.code == "response_invalid"


def test_the_encoder_output_is_compact_utf8_with_one_lf():
    record = contract.decode_launch_response("cancel", line(cancel_response(
        caller_context={"note": "é"})))
    encoded = contract.encode_launch_response(record)
    assert encoded == '{"schema":"placement.launch.cancel.response.v1","request_id":"cn-1",' \
        '"reservation_id":"rsv-1","launch_request_id":"launch-1","state":"cancelled",' \
        '"caller_context":{"note":"é"}}\n'.encode("utf-8")


def test_a_response_line_needs_its_trailing_lf():
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_launch_response("cancel", line(cancel_response())[:-1])
    assert caught.value.code == "input_trailing_data"


def test_exit_class_of_an_unknown_state_is_a_protocol_error():
    import dataclasses
    record = contract.decode_launch_response("cancel", line(cancel_response()))
    with pytest.raises(contract.ProtocolError):
        contract.launch_exit_class(dataclasses.replace(record, state="gone"))
    with pytest.raises(contract.ProtocolError):
        contract.launch_exit_class(object())  # type: ignore[arg-type]


# -- review round 1: encoder failure closure, response framing, branch negatives ------------

def test_the_encoder_refuses_an_unencodable_record_with_a_closed_code():
    record = contract.decode_launch_response("cancel", line(cancel_response()))
    import dataclasses
    bad = dataclasses.replace(record, caller_context={"note": chr(0xD800)})
    with pytest.raises(contract.ProtocolError) as caught:
        contract.encode_launch_response(bad)
    assert caught.value.code == "response_invalid"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.parametrize("member,value", [
    ("evidence.duration_ms", 2 ** 53), ("evidence.renewals", 2 ** 64),
    ("evidence.snapshot.byte_total", 2 ** 63), ("evidence.snapshot.counts.tracked", 2 ** 53 + 1),
])
def test_every_schema_valid_response_the_encoder_emits_decodes(member, value):
    body = at(finished_response(), member, value)
    encoded = contract.encode_launch_response(
        contract.LaunchResponse.from_json(body))
    assert contract.decode_launch_response("launch", encoded).to_json() == body


def test_a_large_schema_valid_response_decodes():
    # Responses have no 64 KiB input bound; that bound is the request rule of x-cli.input.
    body = status_response("finished", caller_context={f"k{i}": "x" * 512 for i in range(16)})
    body["launch"]["caller_context"] = {f"k{i}": "y" * 512 for i in range(16)}
    version = version_response(templates=[
        {"template_id": f"t{i:02d}", "template_sha256": HEX, "workload": "pi-runner"}
        for i in range(64)])
    for verb, value in (("status", body), ("version", version)):
        encoded = contract.encode_launch_response(contract.decode_launch_response(verb, line(value)))
        assert contract.decode_launch_response(verb, encoded).to_json() == value
    assert len(line(body)) > 16384


@pytest.mark.parametrize("framing", [
    lambda b: b + b"\n", lambda b: b[:-1] + b"\r\n", lambda b: b" " + b, lambda b: b[:-1] + b" \n",
    lambda b: b + b"{}\n", lambda b: b[:-1], lambda b: b"\n" + b,
])
def test_a_response_is_exactly_one_line(framing):
    good = line(cancel_response())
    assert contract.decode_launch_response("cancel", good).state == "cancelled"
    with pytest.raises(contract.ProtocolError):
        contract.decode_launch_response("cancel", framing(good))


@pytest.mark.parametrize("data", [
    b'{"schema":"a","schema":"b"}\n', b'{"x":NaN}\n', b'{"x":1e999}\n', b'\xff\n', b'[]\n',
    b'{"x":"\\ud800"}\n',
])
def test_the_response_parser_keeps_the_other_strictness_rules(data):
    with pytest.raises(contract.ProtocolError):
        contract.decode_launch_response("cancel", data)


def test_response_decoding_refuses_non_bytes():
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_launch_response("cancel", "x\n")  # type: ignore[arg-type]
    assert caught.value.code == "input_not_bytes"


# C1 branch negatives for Instructions, each entered from a valid fixture of that form.
INSTRUCTION_FORMS = {
    "none": {"source": "none"},
    "snapshot": {"source": "snapshot", "path": "docs/brief.md"},
    "inline": {"source": "inline", "base64": "aGVsbG8="},
}
INSTRUCTION_NEGATIVES = [
    ("none", {"source": "none", "path": "docs/brief.md"}),
    ("none", {"source": "none", "base64": "aGVsbG8="}),
    ("snapshot", {"source": "snapshot"}),
    ("snapshot", {"source": "snapshot", "path": "/abs/brief.md"}),
    ("snapshot", {"source": "snapshot", "path": "a/../b"}),
    ("snapshot", {"source": "snapshot", "path": 7}),
    ("snapshot", {"source": "snapshot", "path": "docs/brief.md", "base64": "aGVsbG8="}),
    ("inline", {"source": "inline"}),
    ("inline", {"source": "inline", "base64": "not base64!"}),
    ("inline", {"source": "inline", "base64": "A" * 43693}),
    ("inline", {"source": "inline", "base64": "aGVsbG8=", "path": "docs/brief.md"}),
]


@pytest.mark.parametrize("form", sorted(INSTRUCTION_FORMS))
def test_every_instructions_form_decodes(form):
    for build in (remote_pi_request, implementation_request, lambda **c: review_request("leg", **c)):
        body = build(instructions=INSTRUCTION_FORMS[form])
        assert contract.decode_launch_request("launch", raw(body)).to_json() == body
    at_limit = {"source": "inline", "base64": "A" * 43692}
    assert contract.decode_launch_request("launch", raw(remote_pi_request(instructions=at_limit)))


@pytest.mark.parametrize("form,bad", INSTRUCTION_NEGATIVES)
def test_every_instructions_branch_refuses_its_own_violation(form, bad):
    assert contract.decode_launch_request(
        "launch", raw(review_request("leg", instructions=INSTRUCTION_FORMS[form])))
    assert refused("launch", raw(review_request("leg", instructions=bad))) == "schema_invalid"


# Response restrictions not entered above. Where a second clause also refuses the case, the
# overlap is named: such a case shows the message is refused, not which clause refused it.
OMITTED_RESPONSE_CASES = [
    # finished: seed_reason is null outside sandbox_launch_seed_refused (finished code is null).
    ("launch-finished", "seed_reason", "symlink", "seed else-branch only"),
    # uncertain: the uncertain clause and the code else-branches both require null reasons.
    ("launch-uncertain", "snapshot_reason", "dirty_source", "overlaps snapshot else-branch"),
    ("launch-uncertain", "admission_diagnostic", "route_not_qualified",
     "overlaps admission else-branch"),
    ("launch-uncertain", "seed_reason", "symlink", "seed else-branch only"),
    ("launch-uncertain", "code", None, "uncertain code enum only"),
]


@pytest.mark.parametrize("name,path,bad,note", OMITTED_RESPONSE_CASES)
def test_the_remaining_launch_response_restrictions_refuse(name, path, bad, note):
    verb, build = RESPONSES[name]
    response_refused(verb, at(build(), path, bad))


@pytest.mark.parametrize("state", ["queued", "running", "cancelling"])
@pytest.mark.parametrize("member", ["run_id", "scratch_path", "tree_path"])
def test_an_active_status_needs_every_prepared_value(state, member):
    good = status_response(state)
    assert contract.decode_launch_response("status", line(good)).state == state
    response_refused("status", at(good, member, None))


def test_a_seed_manifest_schema_accepts_4096_entries_and_refuses_4097():
    entries = [f"f{i:04d}" for i in range(4096)]
    assert contract.validate_launch_message("SeedManifest", _manifest(*entries))
    assert not contract.validate_launch_message("SeedManifest", _manifest(*entries, "f4096"))
