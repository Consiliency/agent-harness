"""SL-0 production-entry controls; fake host observations, real local BAML.

These fixtures assert a trusted relay, never live T3 route qualification.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from phase_loop_runtime import baml_modular as b
from phase_loop_runtime import review_contract as c
from phase_loop_runtime import review_gateway as g
from phase_loop_runtime import review_t3 as t
from test_review_contract import payload, raw, observe_worker, assert_real_parse


@pytest.fixture(scope="module", autouse=True)
def real_worker():
    b._reset_worker_for_tests(test_mode=True, deadline_s=30, retries=0)
    yield
    b._reset_worker_for_tests()


def capabilities():
    return {"features": {k: True for k in t.REQUIRED_FEATURES},
            "inheritedProviderInstanceId": "provider", "interactionMode": "default",
            "providers": [{"providerInstanceId": "provider", "canRunChildTask": True,
                           "canRunCrossProviderChildTask": True, "constraints": [],
                           "models": [{"id": "model", "options": []}]}]}


@pytest.fixture
def setup(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    scope = {"parent_thread_id": "parent", "checkout": str(checkout)}
    service = g.T3ReviewService(tmp_path / "state", host_scope=scope)
    charter = {"schema": "t3_host_charter.v1", "review_brief": "Inspect the frozen input",
               "host_scope": scope, "allow_correction": True}
    req = service.request(coordinator_key="round/seat", charter=charter,
                          subjects=[{"kind": "document", "sha256": "b" * 64,
                                     "paths": ["contract.md"], "revision": None}],
                          seat="reviewer", source_snapshot=b.snapshot_baml_sources())
    action = service.prepare(req.binding, target={"providerInstanceId": "provider", "model": "model"},
                             capabilities=capabilities())
    return service, req, action


def observation(tool, arguments, result):
    return {"schema": t.OBSERVATION_VERSION, "tool": tool, "arguments": arguments, "result": result}


def registration(service, req, action):
    result = {"taskId": "task-" + req.attempt_id, "childThreadId": "thread-" + req.attempt_id,
              "childRunId": "run-" + req.attempt_id, "providerInstanceId": "provider", "model": "model",
              "status": "completed", "workState": "result_available", "summary": None}
    wrapper = {"schema": t.REGISTRATION_VERSION, "request_binding": req.binding,
               "client_request_id": action.arguments["clientRequestId"],
               "payload_digest": action.payload_digest, "host_scope": service.host_scope,
               "observation": observation("delegate_task", action.arguments, result)}
    service.register(req.binding, wrapper)
    return result


def delivery(service, req, status, body):
    item = {"itemId": "terminal", "position": 7, "runId": status["childRunId"],
            "sourceThreadId": status["childThreadId"], "visibility": "local", "createdBy": "agent",
            "creationSource": "provider", "type": "assistant_message", "status": "completed",
            "updatedAt": "2026-10-19T00:00:00Z", "messageId": "message", "title": None,
            "text": body.decode(), "textTruncated": False, "nextTextOffset": None}
    result = {"thread": {"threadId": status["childThreadId"], "parentThreadId": "parent",
                         "relationshipToParent": "subagent", "worktreePath": service.host_scope["checkout"]},
              "items": [item], "hasMore": False, "nextPosition": 7, "recentRuns": []}
    terminal = {"schema": t.TERMINAL_VERSION, "profile": t.PROFILE_VERSION,
                "request_binding": req.binding, "host_scope": service.host_scope,
                **{k: status[k] for k in t.IDENTITY_KEYS}, "itemId": "terminal", "position": 7,
                "updatedAt": item["updatedAt"]}
    return {"schema": t.INTAKE_VERSION, "terminal": terminal,
            "completion": observation("task_status", {"taskId": status["taskId"]}, status),
            "timeline": [observation("t3_thread_read", {"threadId": status["childThreadId"],
                                                       "view": "messages", "afterPosition": None}, result)],
            "text": [], "evidence_digests": {}}


def test_production_acceptance_and_known_task_resume(setup, monkeypatch):
    service, req, action = setup
    assert action.tool == "delegate_task"
    assert action.arguments["task"].encode() == service.coordinator.build_request(req.binding).prompt.encode()
    status = registration(service, req, action)
    reopened = g.T3ReviewService(service.directory, host_scope=service.host_scope)
    recovery = reopened.resume(req.binding)
    assert recovery.tool == "task_status" and recovery.arguments == {"taskId": status["taskId"]}
    body = raw(payload(req))
    sent, received = observe_worker(monkeypatch)
    record = reopened.intake(req.binding, delivery(service, req, status, body))
    assert record.usable_vote and not record.governed_eligible and record.provenance == "HOST_ATTESTED"
    assert_real_parse(record, sent, received, body, b.snapshot_baml_sources(),
                      reopened.coordinator.private_body(record.record_id))
    again = reopened.resume(req.binding)
    assert again.record_id == record.record_id and len(sent) == 2


@pytest.mark.parametrize("fault", ["original_run", "incomplete", "early_item", "final_cursor", "empty_final"])
def test_production_recovery_gates(setup, fault):
    service, req, action = setup
    status = registration(service, req, action)
    package = delivery(service, req, status, raw(payload(req)))
    page = package["timeline"][0]["result"]
    if fault == "original_run":
        page["items"][0]["runId"] = "later"
    elif fault == "incomplete":
        page["items"][0]["textTruncated"] = True
        page["items"][0]["nextTextOffset"] = t.utf16_length(page["items"][0]["text"])
    elif fault == "early_item":
        page["items"].append({**page["items"][0], "itemId": "later-commentary", "position": 9})
        page["nextPosition"] = 9
    elif fault == "final_cursor":
        page["nextPosition"] = 99
    else:
        page["items"] = []
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        service.intake(req.binding, package)
    assert service.coordinator.validation_history(req.binding) == []


def test_invalid_original_invalid_correction_refused_again_after_restart(setup):
    service, req, action = setup
    status = registration(service, req, action)
    failure = service.intake(req.binding, delivery(service, req, status, b"not JSON"))
    assert failure.rejection_code == "invalid_json"
    correction = service.correction(req.binding, capabilities=capabilities())
    fixed = service.coordinator.correction_request(req.binding)
    assert fixed is not None and fixed.lineage_id == req.lineage_id
    assert correction.arguments["task"] == service.coordinator.build_request(fixed.binding).prompt
    assert correction.arguments["clientRequestId"] != action.arguments["clientRequestId"]
    status = registration(service, fixed, correction)
    failure2 = service.intake(fixed.binding, delivery(service, fixed, status, b"still not JSON"))
    assert not failure2.usable
    reopened = g.T3ReviewService(service.directory, host_scope=service.host_scope)
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        reopened.correction(req.binding, capabilities=capabilities())
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        reopened.correction(fixed.binding, capabilities=capabilities())


def test_gateway_bypass_control(setup, monkeypatch):
    service, req, action = setup
    status = registration(service, req, action)
    package = delivery(service, req, status, raw(payload(req)))
    sent, received = observe_worker(monkeypatch)
    original = service.intake(req.binding, package)
    sent.clear()
    received.clear()
    monkeypatch.setattr(service.coordinator, "revalidate", lambda binding: original)
    monkeypatch.setattr(service.coordinator, "ingest", lambda binding, **kwargs: original)
    cached = service.intake(req.binding, package)
    with pytest.raises(AssertionError, match="bypassed"):
        assert_real_parse(cached, sent, received, raw(payload(req)), b.snapshot_baml_sources(), payload(req))


def test_lost_response_preserves_intent(setup):
    service, req, action = setup
    reopened = g.T3ReviewService(service.directory, host_scope=service.host_scope)
    unresolved = reopened.resume(req.binding)
    assert unresolved.kind == "unresolved" and unresolved.arguments == {}
    assert unresolved.payload_digest == action.payload_digest
    status = registration(reopened, req, action)
    assert reopened.resume(req.binding).arguments == {"taskId": status["taskId"]}


def test_policy_refuses_governed_before_persistence(setup):
    service, req, _ = setup
    class Governed(g.T3NonGatingPolicy):
        def authorize(self, context):
            return replace(super().authorize(context), eligibility="GOVERNED")
    bad = g.T3ReviewService(service.directory, host_scope=service.host_scope,
                            policy=Governed(service.charter))
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        bad.request(coordinator_key="other", charter=service.charter(req.value["brief_digest"]),
                    subjects=req.value["subjects"], seat="other", source_snapshot=b.snapshot_baml_sources())
    with sqlite3.connect(service.coordinator.path) as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1


@pytest.mark.parametrize("fault", ["original_run", "incomplete"])
def test_recovery_bypass_mutation_is_detected(setup, monkeypatch, fault):
    service, req, action = setup
    status = registration(service, req, action)
    good = delivery(service, req, status, raw(payload(req)))
    bad = deepcopy(good)
    item = bad["timeline"][0]["result"]["items"][0]
    if fault == "original_run":
        item["runId"] = "later-run"
    else:
        item["textTruncated"] = True
        item["nextTextOffset"] = t.utf16_length(item["text"])
    with pytest.raises(c.ReviewRefused):
        service.intake(req.binding, bad)
    recover = t.recover
    monkeypatch.setattr(t, "recover", lambda binding, identity, scope, package: recover(binding, identity, scope, good))
    # Removing this boundary makes the matching negative assertion fail.
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        with pytest.raises(c.ReviewRefused):
            service.intake(req.binding, bad)


def split_item(package, first_units):
    result = package["timeline"][0]["result"]
    item = result["items"][0]
    encoded = item["text"].encode("utf-16-le")
    rest = deepcopy(item)
    item["text"] = encoded[:2 * first_units].decode("utf-16-le", "surrogatepass")
    item["textTruncated"], item["nextTextOffset"] = True, first_units
    rest["text"] = encoded[2 * first_units:].decode("utf-16-le", "surrogatepass")
    package["text"] = [observation("t3_thread_read", {"threadId": item["sourceThreadId"], "view": "messages",
                                                    "itemId": item["itemId"], "textOffset": first_units},
                                   {**deepcopy(result), "items": [rest]})]


@pytest.mark.parametrize("replacement", [False, True])
def test_utf16_split_and_replacement_boundary(setup, replacement):
    service, req, action = setup
    status = registration(service, req, action)
    body = raw(payload(req))
    package = delivery(service, req, status, body)
    text = body.decode()
    split_item(package, t.utf16_length(text[:text.index("🐈")]) + 1)
    first = package["timeline"][0]["result"]["items"][0]
    second = package["text"][0]["result"]["items"][0]
    if replacement:
        first["text"] = first["text"][:-1] + "\ufffd"
        second["text"] = "\ufffd" + second["text"][1:]
        with pytest.raises(c.ReviewRefused, match="result_unavailable"):
            service.intake(req.binding, package)
    else:
        # Serialization preserves the split surrogate units, as host files must.
        package = json.loads(t.relay_json(package))
        result = service.intake(req.binding, package)
        assert result.usable_vote and result.body_digest == hashlib.sha256(body).hexdigest()


def test_correction_positive_uses_saved_prompt_and_standing_lineage(setup):
    service, req, action = setup
    status = registration(service, req, action)
    original = service.intake(req.binding, delivery(service, req, status, b"invalid original"))
    action = service.correction(req.binding, capabilities=capabilities())
    correction = service.coordinator.correction_request(req.binding)
    status = registration(service, correction, action)
    result = service.intake(correction.binding, delivery(service, correction, status, raw(payload(correction))))
    assert result.usable_vote and result.replaces_record_id == original.record_id
    assert result.lineage_id == req.lineage_id
    ledger = service.coordinator.build_ledger([req.lineage_id])
    assert len(ledger["lineages"]) == 1


@pytest.mark.parametrize("incomplete", [False, True])
def test_valid_dissent_or_incomplete_never_corrects(setup, incomplete):
    from test_review_contract import finding
    service, req, action = setup
    status = registration(service, req, action)
    value = payload(req, verdict="DISAGREE", findings=[finding(blocking=True)])
    if incomplete:
        value.update(review_status="INCOMPLETE", verdict=None, limitations=["Not enough context"])
    record = service.intake(req.binding, delivery(service, req, status, raw(value)))
    assert record.content_valid and record.usable == (not incomplete)
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        service.correction(req.binding, capabilities=capabilities())
    assert service.coordinator.correction_request(req.binding) is None


def test_state_must_be_outside_checkout_even_through_symlink(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(checkout, target_is_directory=True)
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        g.T3ReviewService(alias / "state", host_scope={"parent_thread_id": "parent", "checkout": str(checkout)})
    assert not (checkout / "state").exists()


@pytest.mark.parametrize("fault", ["feature", "model", "mode", "option", "authority"])
def test_unsupported_dispatch_refuses_without_intent(setup, fault):
    service, req, _ = setup
    charter = service.charter(req.value["brief_digest"])
    other = service.request(coordinator_key="new", charter=charter, subjects=req.value["subjects"],
                            seat="other", source_snapshot=b.snapshot_baml_sources())
    catalog = capabilities()
    target = {"providerInstanceId": "provider", "model": "model"}
    if fault == "feature":
        catalog["features"]["incrementalThreadRead"] = False
    elif fault == "model":
        target["model"] = "unknown"
    elif fault == "mode":
        catalog["interactionMode"] = "plan"
    elif fault == "option":
        target["options"] = {"unknown": True}
    else:
        target["provenance"] = "TRANSPORT_CAPTURED"
    with pytest.raises(c.ReviewRefused):
        service.prepare(other.binding, target=target, capabilities=catalog)
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents WHERE binding=?", (other.binding,)).fetchone()[0] == 0


def test_later_run_metadata_does_not_change_original_delivery(setup):
    service, req, action = setup
    status = registration(service, req, action)
    package = delivery(service, req, status, raw(payload(req)))
    first = service.intake(req.binding, package)
    package["completion"]["result"].update(latestTerminalRunId="later", latestTerminalStatus="failed",
                                         latestTerminalSummary="irrelevant", hasPendingQuestion=True, hasPendingChildRuns=True)
    page = package["timeline"][0]["result"]
    page["items"].append({**page["items"][0], "itemId": "later", "runId": "later", "position": 40, "text": "later summary"})
    page["nextPosition"] = 40
    assert service.intake(req.binding, package).record_id == first.record_id


def test_coordinator_commit_before_intent_is_recoverable(setup):
    service, req, _ = setup
    charter = service.charter(req.value["brief_digest"])
    inputs = dict(coordinator_key="coordinator-only", charter=charter, subjects=req.value["subjects"],
                  seat="crash-seat", source_snapshot=b.snapshot_baml_sources())
    original = service.request(**inputs)
    reopened = g.T3ReviewService(service.directory, host_scope=service.host_scope)
    assert reopened.request(**inputs).binding == original.binding
    action = reopened.prepare(original.binding, target={"providerInstanceId": "provider", "model": "model"},
                              capabilities=capabilities())
    assert action.kind == "dispatch" and reopened.resume(original.binding).kind == "unresolved"


def test_correction_reservation_before_intent_recovers_same_request(setup, monkeypatch):
    service, req, action = setup
    status = registration(service, req, action)
    service.intake(req.binding, delivery(service, req, status, b"invalid"))
    def crash(*args, **kwargs):
        raise RuntimeError("simulated process loss after coordinator commit")
    monkeypatch.setattr(service, "prepare", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        service.correction(req.binding, capabilities=capabilities())
    reserved = service.coordinator.correction_request(req.binding)
    assert reserved is not None
    reopened = g.T3ReviewService(service.directory, host_scope=service.host_scope)
    action = reopened.correction(req.binding, capabilities=capabilities())
    assert action.kind == "dispatch" and action.request_binding == reserved.binding
    again = reopened.correction(req.binding, capabilities=capabilities())
    assert again.kind == "unresolved" and again.payload_digest == action.payload_digest


def test_fake_only_established_deduplication_reemits_identical_payload(setup, monkeypatch):
    service, req, action = setup
    assert t.REDISPATCH_CAPABLE is False
    monkeypatch.setattr(t, "REDISPATCH_CAPABLE", True)
    retried = service.resume(req.binding)
    assert retried.arguments == action.arguments and retried.payload_digest == action.payload_digest
    with pytest.raises(c.ReviewRefused, match="delivery_conflict"):
        catalog = capabilities()
        catalog["providers"][0]["models"].append({"id": "other"})
        service.prepare(req.binding, target={"providerInstanceId": "provider", "model": "other"}, capabilities=catalog)


def test_bounded_authentic_oversize_reaches_coordinator_digest_only(setup):
    service, req, action = setup
    status = registration(service, req, action)
    # This is the complete authentic fixture terminal item, not adapter padding.
    body = b"x" * (c.MAX_BYTES + 1)
    package = delivery(service, req, status, body)
    record = service.intake(req.binding, package)
    assert record.rejection_code == "limit_exceeded" and record.body_digest == hashlib.sha256(body).hexdigest()
    with sqlite3.connect(service.coordinator.path) as db:
        raw_body, transport, omitted = db.execute("SELECT raw,transport,omitted FROM deliveries").fetchone()
        assert raw_body is transport is None and json.loads(omitted)["body_bytes"] == len(body)
    assert service.resume(req.binding).record_id == record.record_id


def test_beyond_recovery_ceiling_never_claims_content_failure(setup):
    service, req, action = setup
    status = registration(service, req, action)
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        service.intake(req.binding, delivery(service, req, status, b"x" * (t.MAX_RECOVERY_BYTES + 1)))
    assert service.coordinator.validation_history(req.binding) == []


@pytest.mark.parametrize("fault", ["null_model", "null_run", "target", "association"])
def test_registration_binding_refuses(setup, fault):
    service, req, action = setup
    status = {"taskId": "task", "childThreadId": "thread", "childRunId": "run",
              "providerInstanceId": "provider", "model": "model"}
    wrapper = {"schema": t.REGISTRATION_VERSION, "request_binding": req.binding,
               "client_request_id": action.arguments["clientRequestId"], "payload_digest": action.payload_digest,
               "host_scope": service.host_scope, "observation": observation("delegate_task", action.arguments, status)}
    if fault == "null_model":
        status["model"] = None
    elif fault == "null_run":
        status["childRunId"] = None
    elif fault == "target":
        status["providerInstanceId"] = "other"
    else:
        wrapper["payload_digest"] = "0" * 64
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        service.register(req.binding, wrapper)
    assert service.resume(req.binding).kind == "unresolved"


def test_timeline_filtered_gaps_and_nonfinal_cursor(setup):
    service, req, action = setup
    status = registration(service, req, action)
    package = delivery(service, req, status, raw(payload(req)))
    page = package["timeline"][0]
    final = deepcopy(page)
    final["arguments"]["afterPosition"] = 5
    first = page["result"]["items"][0]
    first.update(itemId="commentary", position=1, text="Working")
    page["result"].update(hasMore=True, nextPosition=5)
    package["timeline"].append(final)
    assert service.intake(req.binding, package).usable_vote


def test_options_must_be_explicit_and_supported(setup):
    _, req, _ = setup
    catalog = capabilities()
    catalog["providers"][0]["models"][0]["options"] = [
        {"id": "reasoningEffort", "type": "select", "options": [{"id": "high"}, {"id": "low"}]}]
    target = {"providerInstanceId": "provider", "model": "model"}
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        t.dispatch_payload(req.binding, "prompt", target, catalog)
    target["options"] = {"reasoningEffort": "high"}
    assert t.dispatch_payload(req.binding, "prompt", target, catalog)["target"] == target


@pytest.mark.parametrize("fault", ["worker", "parser", "changed_value"])
def test_local_worker_and_bridge_failure_never_reserves_correction(setup, monkeypatch, fault):
    service, req, action = setup
    status = registration(service, req, action)
    parse = b.parse_review_response
    def fail(*args, **kwargs):
        if fault == "worker":
            raise b.BamlWorkerError("timeout", "PRIVATE-DIAGNOSTIC")
        if fault == "parser":
            raise b.BamlValidationError("PRIVATE-DIAGNOSTIC")
        parsed = parse(*args, **kwargs)
        return replace(parsed, value={**parsed.value, "summary": "changed by bridge"})
    monkeypatch.setattr(b, "parse_review_response", fail)
    record = service.intake(req.binding, delivery(service, req, status, raw(payload(req))))
    assert not record.usable
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        service.correction(req.binding, capabilities=capabilities())
    assert service.coordinator.correction_request(req.binding) is None
