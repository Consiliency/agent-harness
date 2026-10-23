"""RT3 fault conformance: synthetic host observations, real local BAML worker.

No provider is dispatched. Mutations exist only to falsify matching assertions;
they cannot establish acceptance or a live redispatch capability.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from phase_loop_runtime import baml_modular as b
from phase_loop_runtime import review_contract as c
from phase_loop_runtime import review_gateway as g
from phase_loop_runtime import review_t3 as t
from test_review_contract import assert_real_parse, observe_worker, payload, raw
from test_review_t3 import capabilities, delivery, registration, split_item, skip_completion_run_comparison


@pytest.fixture(scope="module", autouse=True)
def worker():
    b._reset_worker_for_tests(test_mode=True, deadline_s=30, retries=0)
    yield
    b._reset_worker_for_tests()


@pytest.fixture
def rig(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    scope = {"parent_thread_id": "parent", "checkout": str(checkout)}
    service = g.T3ReviewService(tmp_path / "private", host_scope=scope)
    return service


def create(service, **kwargs):
    charter = {"schema": "t3_host_charter.v1", "review_brief": "Brief café 🐈\nRetain objections.",
               "host_scope": service.host_scope, "allow_correction": True}
    inputs = dict(coordinator_key="fault/seat", charter=charter, seat="seat",
                  subjects=[{"kind": "document", "sha256": "b" * 64, "paths": ["contract.md"], "revision": None}],
                  source_snapshot=b.snapshot_baml_sources())
    return service.request(**{**inputs, **kwargs})


def prepare(service, req):
    return service.prepare(req.binding, target={"providerInstanceId": "provider", "model": "model"},
                           capabilities=capabilities())


def ready(service):
    req = create(service)
    action = prepare(service, req)
    status = registration(service, req, action)
    return req, action, status, delivery(service, req, status, raw(payload(req)))


def reopen(service):
    return g.T3ReviewService(service.directory, host_scope=service.host_scope)


def counts(service):
    with sqlite3.connect(service.coordinator.path) as db:
        return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("requests", "registrations", "deliveries", "records"))


def no_delivery(service, req, package):
    # Preserve the independent malformed source even when an assertion fails.
    (service.directory / "candidate.json").write_bytes(t.relay_json(package))
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        service.intake(req.binding, package)
    assert service.coordinator.validation_history(req.binding) == []
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["taskId", "childThreadId", "childRunId", "providerInstanceId", "model"])
@pytest.mark.parametrize("value", [None, "different"])
def test_completion_identity(rig, field, value):
    req, _, _, package = ready(rig)
    package["completion"]["result"][field] = value
    no_delivery(rig, req, package)


@pytest.mark.parametrize("fault", [
    "missing_status", "missing_work_state", "failed", "running", "question_waiting", "question_queued", "pending_children",
])
def test_original_unfinished_or_failed_cannot_use_later_success(rig, fault):
    req, _, _, package = ready(rig)
    result = package["completion"]["result"]
    result.update(latestTerminalStatus="completed", latestTerminalRunId="later", latestTerminalSummary=raw(payload(req)).decode())
    if fault == "missing_status":
        result.pop("status")
    elif fault == "missing_work_state":
        result.pop("workState")
    elif fault in ("failed", "running"):
        result["status"] = fault
    elif fault.startswith("question_"):
        result.update(status=fault.removeprefix("question_"), workState="working", hasPendingQuestion=True)
    else:
        result.update(workState="waiting_for_children", hasPendingChildRuns=True)
    no_delivery(rig, req, package)


@pytest.mark.parametrize("later", ["failed", "running", "question"])
def test_later_turns_and_misleading_summaries_do_not_replace_original(rig, monkeypatch, later):
    req, _, _, package = ready(rig)
    body = raw(payload(req))
    package["completion"]["result"].update(summary="MISLEADING SUMMARY", latestTerminalRunId="later",
        latestTerminalStatus="failed" if later == "failed" else None, latestTerminalSummary="OTHER SUMMARY",
        hasPendingQuestion=later == "question", hasPendingChildRuns=later != "failed")
    page = package["timeline"][0]
    tail = deepcopy(page)
    tail["arguments"]["afterPosition"] = 7
    tail["result"]["items"][0].update(itemId="later", runId="later", position=40, text="OTHER SUMMARY")
    tail["result"]["thread"]["status"] = "waiting" if later == "question" else later
    tail["result"]["thread"]["pendingRequestCount"] = int(later == "question")
    tail["result"]["nextPosition"] = 40
    page["result"].update(hasMore=True, nextPosition=7)
    package["timeline"].append(tail)
    sent, received = observe_worker(monkeypatch)
    record = rig.intake(req.binding, package)
    assert_real_parse(record, sent, received, body, b.snapshot_baml_sources(), rig.coordinator.private_body(record.record_id))
    assert record.usable_vote and not record.governed_eligible
    assert reopen(rig).resume(req.binding).record_id == record.record_id


@pytest.mark.parametrize("field,value", [
    ("sourceThreadId", "other"), ("runId", "other"), ("visibility", "inherited"),
    ("creationSource", "synthetic"), ("createdBy", "user"), ("type", "tool_result"),
    ("status", "running"), ("updatedAt", "changed"), ("position", 8), ("itemId", "missing"),
])
def test_selected_item_identity(rig, field, value):
    req, _, _, package = ready(rig)
    package["timeline"][0]["result"]["items"][0][field] = value
    no_delivery(rig, req, package)


@pytest.mark.parametrize("field,value", [
    ("threadId", "other"), ("parentThreadId", "other"), ("relationshipToParent", "fork"),
    ("worktreePath", "/"), ("worktreePath", None),
])
def test_read_scope(rig, field, value):
    req, _, _, package = ready(rig)
    package["timeline"][0]["result"]["thread"][field] = value
    no_delivery(rig, req, package)


@pytest.mark.parametrize("fault", ["profile", "binding", "attestation_scope", "attestation_run", "schema", "summary_only"])
def test_attestation_is_required_and_bound(rig, fault):
    req, _, _, package = ready(rig)
    if fault == "summary_only":
        package["timeline"] = []
        package["completion"]["result"]["summary"] = raw(payload(req)).decode()
    elif fault == "schema":
        package["schema"] = "unknown"
    else:
        key = {"binding": "request_binding", "attestation_scope": "host_scope", "attestation_run": "childRunId"}.get(fault, fault)
        package["terminal"][key] = "other"
    no_delivery(rig, req, package)


@pytest.mark.parametrize("fault", [
    "duplicate_id", "duplicate_position", "backwards", "skip_cursor", "loop", "unfinished",
    "extra_page", "empty_final", "bad_final", "earlier_assistant", "missing_first", "recent_run",
])
def test_timeline_coverage_faults(rig, fault):
    req, _, status, package = ready(rig)
    first = package["timeline"][0]
    tail = deepcopy(first)
    tail["arguments"]["afterPosition"] = 7
    tail["result"]["items"][0].update(itemId="tail", position=40, runId="later")
    tail["result"]["nextPosition"] = 40
    first["result"].update(hasMore=True, nextPosition=7)
    package["timeline"].append(tail)
    item = tail["result"]["items"][0]
    if fault == "duplicate_id":
        item["itemId"] = "terminal"
    elif fault == "duplicate_position":
        item["position"] = 7
    elif fault == "backwards":
        item["position"] = 1
    elif fault == "skip_cursor":
        tail["arguments"]["afterPosition"] = 8
    elif fault == "loop":
        tail["result"].update(hasMore=True, nextPosition=7)
    elif fault == "unfinished":
        package["timeline"].pop()
    elif fault == "extra_page":
        first["result"]["hasMore"] = False
    elif fault == "empty_final":
        tail["result"]["items"] = []
    elif fault == "bad_final":
        tail["result"]["nextPosition"] = 41
    elif fault == "earlier_assistant":
        # Same exposed type as commentary: only full original-run traversal
        # can falsify the host's claim that the earlier item was terminal.
        item["runId"] = status["childRunId"]
    elif fault == "missing_first":
        first["arguments"]["afterPosition"] = 3
    else:
        tail["result"]["recentRuns"] = [{"runId": status["childRunId"], "status": "failed",
                                          "model": "model", "providerInstanceId": "provider"}]
    no_delivery(rig, req, package)


@pytest.mark.parametrize("final_cursor", [None, 40])
def test_filtered_gaps_and_global_final_cursor(rig, final_cursor):
    req, _, _, package = ready(rig)
    terminal = package["timeline"][0]
    commentary = deepcopy(terminal)
    commentary["result"]["items"][0].update(itemId="commentary", position=1, text="Working")
    commentary["result"].update(hasMore=True, nextPosition=5)
    terminal["arguments"]["afterPosition"] = 5
    terminal["result"].update(hasMore=True, nextPosition=7)
    last = deepcopy(terminal)
    last["arguments"]["afterPosition"] = 7
    last["result"]["items"][0].update(itemId="later", runId="later", position=40)
    last["result"].update(hasMore=False, nextPosition=final_cursor)
    package["timeline"] = [commentary, terminal, last]
    assert rig.intake(req.binding, package).usable_vote


@pytest.mark.parametrize("fault", [
    "gap", "overlap", "codepoints", "missing_chunk", "extra_chunk", "non_null_final", "empty_chunk",
    "changed_title", "changed_time", "changed_message", "changed_item", "changed_position",
    "replacement_left", "replacement_right", "replacement_pair", "lone_high", "lone_low",
])
def test_utf16_and_mutable_item_faults(rig, fault):
    req, _, _, package = ready(rig)
    full = package["timeline"][0]["result"]["items"][0]["text"]
    cut = t.utf16_length(full[:full.index("🐈")]) + 1
    split_item(package, cut)
    first = package["timeline"][0]["result"]["items"][0]
    last = package["text"][0]["result"]["items"][0]
    if fault in ("gap", "overlap"):
        package["text"][0]["arguments"]["textOffset"] += 1 if fault == "gap" else -1
    elif fault == "codepoints":
        split_item(package := delivery(rig, req, package["completion"]["result"], raw(payload(req))), cut + 1)
        package["timeline"][0]["result"]["items"][0]["nextTextOffset"] = cut
    elif fault == "missing_chunk":
        package["text"] = []
    elif fault == "extra_chunk":
        package["text"].append(deepcopy(package["text"][0]))
    elif fault == "non_null_final":
        last["nextTextOffset"] = cut + t.utf16_length(last["text"])
    elif fault == "empty_chunk":
        last["text"] = ""
    elif fault.startswith("changed_"):
        key = {"title": "title", "time": "updatedAt", "message": "messageId", "item": "itemId", "position": "position"}[fault[8:]]
        last[key] = 8 if key == "position" else "changed"
    elif fault.startswith("replacement"):
        if fault in ("replacement_left", "replacement_pair"):
            first["text"] = first["text"][:-1] + "\ufffd"
        if fault in ("replacement_right", "replacement_pair"):
            last["text"] = "\ufffd" + last["text"][1:]
    elif fault == "lone_high":
        last["text"] = "x" + last["text"][1:]
    else:
        first["text"] = first["text"][:-1] + "x"
    no_delivery(rig, req, package)


@pytest.mark.parametrize("split", [False, True])
def test_original_bytes_and_observations_preserved(rig, monkeypatch, split):
    req, _, status, _ = ready(rig)
    body = raw(payload(req, summary='Line\r\n café 🐈 literal \\u1234 and genuine � inside'))
    package = delivery(rig, req, status, body)
    if split:
        text = body.decode()
        split_item(package, t.utf16_length(text[:text.index("🐈")]) + 1)
    package = json.loads(t.relay_json(package))
    sent, received = observe_worker(monkeypatch)
    record = rig.intake(req.binding, package)
    assert_real_parse(record, sent, received, body, b.snapshot_baml_sources(), rig.coordinator.private_body(record.record_id))
    with sqlite3.connect(rig.path) as db:
        saved, envelope, observations = db.execute("SELECT body,envelope,observations FROM deliveries").fetchone()
    assert saved == body and observations == t.relay_json(package)
    assert json.loads(envelope)["body"].encode() == body
    assert record.body_digest == hashlib.sha256(body).hexdigest()
    assert len(envelope) <= 6 * len(body) + 65536


@pytest.mark.parametrize("limit", ["timeline", "text", "items", "metadata", "observation", "retained", "utf8"])
def test_finite_recovery_bounds(rig, limit):
    req, _, _, package = ready(rig)
    page = package["timeline"][0]
    if limit == "timeline":
        package["timeline"] *= t.MAX_TIMELINE_PAGES + 1
    elif limit == "text":
        package["text"] = [page] * (t.MAX_TEXT_PAGES + 1)
    elif limit == "items":
        page["result"]["items"] = [{"itemId": str(i), "position": i} for i in range(t.MAX_ITEMS + 1)]
    elif limit == "metadata":
        page["result"]["items"][0]["title"] = "x" * (t.MAX_METADATA_BYTES + 1)
    elif limit == "observation":
        page["result"]["unused"] = "x" * t.MAX_OBSERVATION_BYTES
    elif limit == "retained":
        package["evidence_digests"] = {"unused": "x" * t.MAX_RETAINED_BYTES}
    else:
        # Below the UTF-16-unit ceiling, above the independent UTF-8 ceiling.
        page["result"]["items"][0]["text"] = "é" * (t.MAX_RECOVERY_BYTES // 2 + 1)
    no_delivery(rig, req, package)


@pytest.mark.parametrize("change", [
    {"eligibility": "GOVERNED"}, {"governed_provenance": ("HOST_ATTESTED",)},
    {"permitted_provenance": ("TRANSPORT_CAPTURED",)}, {"unusable_seat_blocks": False},
])
def test_injected_policy_rejected_before_request_commit(rig, change):
    class Incompatible(g.T3NonGatingPolicy):
        def authorize(self, context):
            return replace(super().authorize(context), **change)
    service = g.T3ReviewService(rig.directory, host_scope=rig.host_scope, policy=Incompatible(rig.charter))
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        create(service)
    assert counts(service) == (0, 0, 0, 0)


@pytest.mark.parametrize("fault", ["child_disabled", "cross_disabled", "constraint", "duplicate_provider",
    "duplicate_model", "unknown_option_type", "missing_option", "bad_boolean", "bad_select", "capability_size"])
def test_capability_refusal_precedes_intent(rig, fault):
    req = create(rig)
    catalog = capabilities()
    provider = catalog["providers"][0]
    model = provider["models"][0]
    target = {"providerInstanceId": "provider", "model": "model"}
    if fault == "child_disabled":
        provider["canRunChildTask"] = False
    elif fault == "cross_disabled":
        catalog["inheritedProviderInstanceId"] = "other"
        provider["canRunCrossProviderChildTask"] = False
    elif fault == "constraint":
        provider["constraints"] = ["not available"]
    elif fault == "duplicate_provider":
        catalog["providers"].append(deepcopy(provider))
    elif fault == "duplicate_model":
        provider["models"].append(deepcopy(model))
    elif fault == "capability_size":
        catalog["unused"] = "x" * t.MAX_CAPABILITY_BYTES
    else:
        model["options"] = [{"id": "option", "type": "boolean"}]
        target["options"] = {"option": True}
        if fault == "unknown_option_type":
            model["options"][0]["type"] = "number"
        elif fault == "missing_option":
            target.pop("options")
        elif fault == "bad_boolean":
            target["options"]["option"] = 1
        else:
            model["options"][0].update(type="select", options=[{"id": "high"}])
            target["options"]["option"] = "unknown"
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        rig.prepare(req.binding, target=target, capabilities=catalog)
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


def test_all_declared_options_are_explicit_and_correction_preserves_them(rig):
    req = create(rig)
    catalog = capabilities()
    catalog["providers"][0]["models"][0]["options"] = [
        {"id": "effort", "type": "select", "options": [{"id": "high"}]},
        {"id": "enabled", "type": "boolean"},
    ]
    target = {"providerInstanceId": "provider", "model": "model", "options": {"effort": "high", "enabled": False}}
    action = rig.prepare(req.binding, target=target, capabilities=catalog)
    assert action.arguments["target"] == target
    status = registration(rig, req, action)
    rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
    corrected = rig.correction(req.binding, capabilities=catalog)
    assert corrected.arguments["target"] == target
    assert corrected.arguments["task"].encode() == rig.coordinator.build_request(corrected.request_binding).prompt.encode()


def alternate_target(target, catalog, change):
    target, catalog = deepcopy(target), deepcopy(catalog)
    if change == "provider":
        provider = deepcopy(catalog["providers"][0])
        provider["providerInstanceId"] = target["providerInstanceId"] = "other-provider"
        catalog["providers"].append(provider)
    elif change == "model":
        model = deepcopy(catalog["providers"][0]["models"][0])
        model["id"] = target["model"] = "other-model"
        catalog["providers"][0]["models"].append(model)
    else:
        target["options"]["effort"] = "low"
    return target, catalog


def option_target():
    catalog = capabilities()
    catalog["providers"][0]["models"][0]["options"] = [
        {"id": "effort", "type": "select", "options": [{"id": "high"}, {"id": "low"}]}]
    return {"providerInstanceId": "provider", "model": "model", "options": {"effort": "high"}}, catalog


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("change", ["provider", "model", "options"])
def test_correction_prepare_target_binding(rig, monkeypatch, existing, change):
    req = create(rig)
    target, catalog = option_target()
    action = rig.prepare(req.binding, target=target, capabilities=catalog)
    status = registration(rig, req, action)
    rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
    if existing:
        saved = rig.correction(req.binding, capabilities=catalog)
    else:
        with monkeypatch.context() as patch:
            patch.setattr(rig, "prepare", crash)
            with pytest.raises(SystemExit):
                rig.correction(req.binding, capabilities=catalog)
    reserved = rig.coordinator.correction_request(req.binding)
    changed, fresh = alternate_target(target, catalog, change)
    service = reopen(rig)
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        service.prepare(reserved.binding, target=changed, capabilities=fresh)
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents WHERE binding=?", (reserved.binding,)).fetchone()[0] == int(existing)
    assert service.coordinator.correction_request(req.binding).binding == reserved.binding
    recovered = service.prepare(reserved.binding, target=target, capabilities=catalog)
    assert recovered.kind == ("unresolved" if existing else "dispatch")
    if existing:
        assert recovered.payload_digest == saved.payload_digest
    else:
        assert recovered.arguments["target"] == target
    assert service.correction(req.binding, capabilities=catalog).kind == "unresolved"


def status_registration(service, req, action, status):
    return {"schema": t.REGISTRATION_VERSION, "request_binding": req.binding,
            "client_request_id": action.arguments["clientRequestId"], "payload_digest": action.payload_digest,
            "host_scope": service.host_scope, "observation": {
                "schema": t.OBSERVATION_VERSION, "tool": "task_status",
                "arguments": {"taskId": status["taskId"]}, "result": status}}


def test_first_status_registration_and_local_refusal_budget(rig):
    req, _, status, _ = ready(rig)
    other = create(rig, coordinator_key="other")
    action = prepare(rig, other)
    assert reopen(rig).resume(other.binding).kind == "unresolved"
    with pytest.raises(c.ReviewRefused, match="delivery_conflict"):
        reopen(rig).register(other.binding, status_registration(rig, other, action, status))
    assert rig.coordinator.validation_history(other.binding) == []
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        rig.correction(other.binding, capabilities=capabilities())
    assert rig.coordinator.correction_request(other.binding) is None
    correct = {**status, **{k: "other-" + status[k] for k in t.IDENTITY_KEYS}}
    wrapper = status_registration(rig, other, action, correct)
    first = reopen(rig).register(other.binding, wrapper)
    assert reopen(rig).register(other.binding, wrapper) == first
    assert reopen(rig).resume(other.binding).arguments == {"taskId": correct["taskId"]}
    assert rig.intake(other.binding, delivery(rig, other, correct, raw(payload(other)))).usable_vote
    assert rig.coordinator.correction_request(req.binding) is None


@pytest.mark.parametrize("collision", ["taskId", "childThreadId", "childRunId", "all"])
@pytest.mark.parametrize("correction", [False, True])
def test_cross_binding_registration_identity(rig, collision, correction):
    req, _, status, _ = ready(rig)
    if correction:
        rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
        action = rig.correction(req.binding, capabilities=capabilities())
        other = rig.coordinator.correction_request(req.binding)
    else:
        other = create(rig, coordinator_key="other")
        action = prepare(rig, other)
    candidate = {**status, **{k: "other-" + status[k] for k in t.IDENTITY_KEYS}}
    for key in t.IDENTITY_KEYS if collision == "all" else [collision]:
        candidate[key] = status[key]
    with pytest.raises(c.ReviewRefused, match="delivery_conflict"):
        reopen(rig).register(other.binding, status_registration(rig, other, action, candidate))
    assert rig.resume(other.binding).kind == "unresolved"
    assert rig.coordinator.validation_history(other.binding) == []
    assert (rig.coordinator.correction_request(req.binding).binding if correction else None) == (other.binding if correction else None)


def test_concurrent_first_status_registration(rig):
    requests = [create(rig, coordinator_key=f"seat-{i}") for i in range(2)]
    actions = [prepare(rig, req) for req in requests]
    status = {"taskId": "same-task", "childThreadId": "same-thread", "childRunId": "same-run",
              "providerInstanceId": "provider", "model": "model"}
    barrier = Barrier(2)
    def register_first(index):
        service = reopen(rig)
        barrier.wait(timeout=30)
        try:
            return service.register(requests[index].binding,
                status_registration(service, requests[index], actions[index], status))["provenance"]
        except c.ReviewRefused as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register_first, range(2)))
    assert sorted(results) == ["HOST_ATTESTED", "delivery_conflict"]
    assert counts(rig) == (2, 1, 0, 0)


@pytest.mark.parametrize("choices", ["hi", ["hi"], None, {}, [None], [{}], [{"id": ""}], [{"id": 1}],
                                     [{"id": "high"}, {"id": "high"}], [{"id": "high"}, "bad"],
                                     [{"id": "high"}, {"id": None}]])
def test_malformed_select_options_refuse_before_intent(rig, choices):
    req = create(rig)
    target, catalog = option_target()
    catalog["providers"][0]["models"][0]["options"][0]["options"] = choices
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        rig.prepare(req.binding, target=target, capabilities=catalog)
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize("declared", ["", {}, False, 0, ["bad"], [None], [{}]])
def test_malformed_model_option_declarations(rig, declared):
    req = create(rig)
    catalog = capabilities()
    catalog["providers"][0]["models"][0]["options"] = declared
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        rig.prepare(req.binding, target={"providerInstanceId": "provider", "model": "model"}, capabilities=catalog)
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize("mode", [None, "inherit", "unknown", {}, False])
def test_runtime_mode_required_before_fresh_intent(rig, mode):
    req = create(rig)
    catalog = capabilities()
    if mode is None:
        catalog.pop("runtimeMode")
    else:
        catalog["runtimeMode"] = mode
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        rig.prepare(req.binding, target={"providerInstanceId": "provider", "model": "model"}, capabilities=catalog)
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["approval-required", "auto-accept-edits", "auto", "full-access"])
def test_runtime_mode_bound_on_fresh_prepare_and_reopen(rig, mode):
    req = create(rig)
    catalog = {**capabilities(), "runtimeMode": mode}
    target = {"providerInstanceId": "provider", "model": "model"}
    action = rig.prepare(req.binding, target=target, capabilities=catalog)
    assert action.kind == "dispatch" and "runtimeMode" not in action.arguments
    fresh = {**catalog, "runtimeMode": "auto" if mode != "auto" else "full-access"}
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        reopen(rig).prepare(req.binding, target=target, capabilities=fresh)
    assert reopen(rig).prepare(req.binding, target=target, capabilities=catalog).kind == "unresolved"
    with sqlite3.connect(rig.path) as db:
        assert json.loads(db.execute("SELECT capabilities FROM intents").fetchone()[0])["runtimeMode"] == mode


@pytest.mark.parametrize("boundary", ["before_reservation", "reserved", "prepared", "offered", "registered"])
def test_correction_runtime_mode_changes_refuse_before_action(rig, monkeypatch, boundary):
    req, action, status, _ = ready(rig)
    rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
    if boundary in ("reserved", "prepared"):
        with monkeypatch.context() as patch:
            patch.setattr(rig, "prepare" if boundary == "reserved" else "_offer", crash)
            with pytest.raises(SystemExit):
                rig.correction(req.binding, capabilities=capabilities())
    elif boundary in ("offered", "registered"):
        corrected = rig.correction(req.binding, capabilities=capabilities())
        if boundary == "registered":
            registration(rig, rig.coordinator.correction_request(req.binding), corrected)
    reserved = rig.coordinator.correction_request(req.binding)
    with sqlite3.connect(rig.path) as db:
        before = db.execute("SELECT * FROM intents ORDER BY binding").fetchall()
    fresh = {**capabilities(), "runtimeMode": "approval-required"}
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        reopen(rig).correction(req.binding, capabilities=fresh)
    if reserved is not None:
        with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
            reopen(rig).prepare(reserved.binding, target=action.arguments["target"], capabilities=fresh)
        assert rig.coordinator.correction_request(req.binding).binding == reserved.binding
    else:
        assert rig.coordinator.correction_request(req.binding) is None
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT * FROM intents ORDER BY binding").fetchall() == before
    recovered = reopen(rig).correction(req.binding, capabilities=capabilities())
    assert recovered.kind == ("recover" if boundary == "registered" else "unresolved" if boundary == "offered" else "dispatch")
    if reserved is not None:
        assert recovered.request_binding == reserved.binding


def test_null_launch_run_retains_unresolved_then_status_host_assertion(rig):
    req = create(rig)
    action = prepare(rig, req)
    status = {"taskId": "task", "childThreadId": "thread", "childRunId": None,
              "providerInstanceId": "provider", "model": "model"}
    wrapper = status_registration(rig, req, action, status)
    wrapper["observation"].update(tool="delegate_task", arguments=action.arguments)
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        rig.register(req.binding, wrapper)
    assert reopen(rig).resume(req.binding).kind == "unresolved"
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT registration FROM intents").fetchone()[0] is None
    # No echoed clientRequestId is invented in task_status. Association is the
    # host's wrapper assertion, not a two-observation correlation protocol.
    status = {**status, "childRunId": "run", "status": "completed", "workState": "result_available"}
    wrapper = status_registration(rig, req, action, status)
    assert "clientRequestId" not in wrapper["observation"]["result"]
    assert reopen(rig).register(req.binding, wrapper)["provenance"] == "HOST_ATTESTED"
    assert rig.intake(req.binding, delivery(rig, req, status, raw(payload(req)))).usable_vote


@pytest.mark.parametrize("override", ["isolation", "runtimeMode", "role", "mode", "profile", "provenance"])
def test_unsupported_dispatch_overrides_never_create_intent(rig, override):
    req = create(rig)
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        rig.prepare(req.binding, target={"providerInstanceId": "provider", "model": "model", override: "unsupported"},
                    capabilities=capabilities())
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


def test_over_ceiling_prompt_never_creates_intent(rig, monkeypatch):
    req = create(rig)
    built = rig.coordinator.build_request(req.binding)
    # Negative builder observation only; a fabricated prompt is never accepted.
    monkeypatch.setattr(rig.coordinator, "build_request", lambda binding: replace(built, prompt="x" * (t.MAX_PROMPT_BYTES + 1)))
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        prepare(rig, req)
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["taskId", "childThreadId", "childRunId"])
def test_registered_identity_is_immutable(rig, field):
    req, action, status, _ = ready(rig)
    result = {**status, field: "replacement"}
    wrapper = {"schema": t.REGISTRATION_VERSION, "request_binding": req.binding,
               "client_request_id": action.arguments["clientRequestId"], "payload_digest": action.payload_digest,
               "host_scope": rig.host_scope, "observation": {
                   "schema": t.OBSERVATION_VERSION, "tool": "delegate_task", "arguments": action.arguments, "result": result}}
    with pytest.raises(c.ReviewRefused, match="delivery_conflict"):
        reopen(rig).register(req.binding, wrapper)
    assert reopen(rig).resume(req.binding).arguments == {"taskId": status["taskId"]}


def test_correction_preflight_refusal_does_not_spend_allowance(rig):
    req, _, status, _ = ready(rig)
    rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
    unavailable = capabilities()
    unavailable["features"]["incrementalThreadRead"] = False
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        rig.correction(req.binding, capabilities=unavailable)
    assert rig.coordinator.correction_request(req.binding) is None
    assert rig.correction(req.binding, capabilities=capabilities()).kind == "dispatch"


def crash(*args, **kwargs):
    raise SystemExit(23)


@pytest.mark.parametrize("boundary", ["request", "prepared", "offered", "registration", "delivery", "coordinator_delivery", "reservation"])
def test_crash_restart_boundaries(rig, monkeypatch, boundary):
    if boundary == "request":
        with monkeypatch.context() as patch:
            original = rig.coordinator.create_request
            def commit_then_die(**kwargs):
                original(**kwargs)
                crash()
            patch.setattr(rig.coordinator, "create_request", commit_then_die)
            with pytest.raises(SystemExit):
                create(rig)
        service = reopen(rig)
        req = create(service)
        assert counts(service)[0] == 1
        assert prepare(service, req).kind == "dispatch"
        assert service.resume(req.binding).kind == "unresolved"
        return
    req = create(rig)
    if boundary == "prepared":
        with monkeypatch.context() as patch:
            patch.setattr(rig, "_offer", crash)
            with pytest.raises(SystemExit):
                prepare(rig, req)
        service = reopen(rig)
        action = service.resume(req.binding)
        assert action.kind == "dispatch"
        assert service.resume(req.binding).kind == "unresolved"
        assert counts(service) == (1, 0, 0, 0)
        return
    action = prepare(rig, req)
    if boundary == "offered":
        service = reopen(rig)
        assert service.resume(req.binding).kind == "unresolved"
        assert prepare(service, req).kind == "unresolved"
        status = registration(service, req, action)
        assert service.resume(req.binding).arguments == {"taskId": status["taskId"]}
        return
    if boundary == "registration":
        with monkeypatch.context() as patch:
            patch.setattr(rig.coordinator, "register_transport", crash)
            with pytest.raises(SystemExit):
                registration(rig, req, action)
        assert counts(rig) == (1, 0, 0, 0)
        service = reopen(rig)
        assert service.resume(req.binding).kind == "recover"
        assert counts(service) == (1, 1, 0, 0)
        return
    status = registration(rig, req, action)
    if boundary == "reservation":
        rig.intake(req.binding, delivery(rig, req, status, b"invalid original"))
        with monkeypatch.context() as patch:
            patch.setattr(rig, "prepare", crash)
            with pytest.raises(SystemExit):
                rig.correction(req.binding, capabilities=capabilities())
        reserved = rig.coordinator.correction_request(req.binding)
        service = reopen(rig)
        assert service.correction(req.binding, capabilities=capabilities()).request_binding == reserved.binding
        assert service.correction(req.binding, capabilities=capabilities()).kind == "unresolved"
        assert counts(service)[0] == 2
        return
    body = raw(payload(req))
    with monkeypatch.context() as patch:
        patch.setattr(rig if boundary == "delivery" else rig.coordinator,
                      "_accept" if boundary == "delivery" else "_validate", crash)
        with pytest.raises(SystemExit):
            rig.intake(req.binding, delivery(rig, req, status, body))
    service = reopen(rig)
    record = service.resume(req.binding)
    assert record.usable_vote and record.body_digest == hashlib.sha256(body).hexdigest()
    assert service.resume(req.binding).record_id == record.record_id
    assert counts(service) == (1, 1, 1, 1)


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_intake(rig, conflicting):
    req, _, status, package = ready(rig)
    packages = [package, deepcopy(package), delivery(rig, req, status, raw(payload(req, summary="other"))) if conflicting else package]
    barrier = Barrier(3)
    def accept(candidate):
        service = reopen(rig)
        barrier.wait(timeout=30)
        try:
            return service.intake(req.binding, candidate).record_id
        except c.ReviewRefused as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(accept, packages))
    if conflicting:
        assert results.count("delivery_conflict") in (1, 2)
    else:
        assert "delivery_conflict" not in results
    assert len(set(results) - {"delivery_conflict"}) == 1
    assert counts(rig) == (1, 1, 1, 1)


def test_concurrent_correction_reservation(rig):
    req, _, status, _ = ready(rig)
    rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
    barrier = Barrier(3)
    def reserve(_):
        service = reopen(rig)
        barrier.wait(timeout=30)
        return service.correction(req.binding, capabilities=capabilities())
    with ThreadPoolExecutor(max_workers=3) as pool:
        actions = list(pool.map(reserve, range(3)))
    assert len({a.request_binding for a in actions}) == len({a.payload_digest for a in actions}) == 1
    assert [a.kind for a in actions].count("dispatch") == 1
    assert [a.kind for a in actions].count("unresolved") == 2
    assert counts(rig)[0] == 2


@pytest.mark.parametrize("lens", [None, "Arbitrary research / design lens 🐈"])
def test_saved_source_replay_and_stable_identity(rig, monkeypatch, lens):
    source = b.snapshot_baml_sources()
    req = create(rig, lens=lens)
    status = registration(rig, req, prepare(rig, req))
    body = raw(payload(req))
    record = rig.intake(req.binding, delivery(rig, req, status, body))
    changed = dict(source.files)
    changed["review_reply.baml"] += "\n// unrelated installed source change\n"
    installed = b.BamlSourceSnapshot(changed)
    assert installed.fingerprint != source.fingerprint
    # Change only installed-source acquisition. Saved-map restoration must
    # continue to use its explicit files argument through the real function.
    monkeypatch.setattr(b, "_snapshot_files", lambda: changed)
    sent, received = observe_worker(monkeypatch)
    replay = reopen(rig).resume(req.binding)
    assert replay.record_id == record.record_id
    # Stable records retain their first IPC id. The validation history, not a
    # rewritten receipt, must bind the actual fresh worker invocation.
    assert replay.ipc_id == record.ipc_id
    assert len(sent) == len(received) == 1, "replay bypassed the actual worker"
    rid, operation, text, fingerprint = sent[0]
    frame = received[0]
    history = rig.coordinator.validation_history(req.binding)
    assert len(history) == 2
    current = history[-1]
    assert current["result_record_id"] == replay.record_id
    assert current["invocation"]["ipc_id"] == frame["id"] == rid
    assert current["invocation"]["operation"] == frame["operation"] == operation == "parse_review_reply"
    assert current["invocation"]["contract_fingerprint"] == frame["fingerprint"] == fingerprint == source.fingerprint
    assert text.encode() == body
    assert c.strict_tree_equal(rig.coordinator.private_body(record.record_id), json.loads(frame["ok"]))
    assert current["invocation"]["parsed_digest"] == hashlib.sha256(c.canonical_json(json.loads(frame["ok"]))).hexdigest()


@pytest.mark.parametrize("fault", ["worker", "bridge", "changed"])
def test_current_revalidation_failure_and_local_recovery(rig, monkeypatch, fault):
    req, _, _, package = ready(rig)
    original = rig.intake(req.binding, package)
    parse = b.parse_review_response
    def fail(*args, **kwargs):
        if fault == "worker":
            raise b.BamlWorkerError("timeout", "PRIVATE")
        if fault == "bridge":
            raise b.BamlValidationError("PRIVATE")
        return replace(parse(*args, **kwargs), value={**payload(req), "summary": "changed"})
    with monkeypatch.context() as patch:
        patch.setattr(b, "parse_review_response", fail)
        current = reopen(rig).resume(req.binding)
        assert not current.usable and current.record_id != original.record_id
        with pytest.raises(c.ReviewRefused, match="result_unavailable"):
            rig.correction(req.binding, capabilities=capabilities())
        assert rig.coordinator.correction_request(req.binding) is None
    assert reopen(rig).resume(req.binding).record_id == original.record_id


@pytest.mark.parametrize("correction", [False, True])
@pytest.mark.parametrize("size", [c.MAX_BYTES + 1, t.MAX_RECOVERY_BYTES, t.MAX_RECOVERY_BYTES + 1])
def test_authentic_oversize_at_original_and_correction_entry(rig, correction, size):
    req, _, status, _ = ready(rig)
    original = req
    if correction:
        first = rig.intake(req.binding, delivery(rig, req, status, b"invalid original"))
        action = rig.correction(req.binding, capabilities=capabilities())
        req = rig.coordinator.correction_request(original.binding)
        status = registration(rig, req, action)
    body = b"x" * size  # The complete synthetic host item; no recovery padding.
    package = delivery(rig, req, status, body)
    if size > t.MAX_RECOVERY_BYTES:
        with pytest.raises(c.ReviewRefused, match="result_unavailable"):
            rig.intake(req.binding, package)
        assert rig.coordinator.validation_history(req.binding) == []
        assert reopen(rig).resume(req.binding).kind == "recover"
        return
    record = rig.intake(req.binding, package)
    assert record.rejection_code == "limit_exceeded" and record.ipc_id is None
    assert record.body_digest == hashlib.sha256(body).hexdigest()
    with sqlite3.connect(rig.coordinator.path) as db:
        stored, envelope, omitted = db.execute("SELECT raw,transport,omitted FROM deliveries WHERE binding=?", (req.binding,)).fetchone()
        assert stored is envelope is None
        assert json.loads(omitted)["body_bytes"] == size
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT body FROM deliveries WHERE binding=?", (req.binding,)).fetchone()[0] == body
    assert reopen(rig).resume(req.binding).record_id == record.record_id
    if correction:
        assert record.replaces_record_id == first.record_id
        with pytest.raises(c.ReviewRefused, match="result_unavailable"):
            reopen(rig).correction(original.binding, capabilities=capabilities())


def test_missing_saved_source_never_reuses_vote(rig):
    req, _, _, package = ready(rig)
    assert rig.intake(req.binding, package).usable_vote
    # Deliberate fixture corruption; production calls never edit coordinator SQL.
    with sqlite3.connect(rig.coordinator.path) as db:
        db.execute("DELETE FROM sources")
    with pytest.raises(c.ReviewRefused, match="baml_unavailable"):
        reopen(rig).resume(req.binding)


def test_changed_policy_never_reuses_vote(rig):
    req, _, _, package = ready(rig)
    assert rig.intake(req.binding, package).usable_vote
    class Changed(g.T3NonGatingPolicy):
        identity = "f" * 64
    changed = g.T3ReviewService(rig.directory, host_scope=rig.host_scope, policy=Changed(rig.charter))
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        changed.resume(req.binding)


def test_orphan_charter_does_not_authorize_dispatch(rig, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(rig.coordinator, "create_request", crash)
        with pytest.raises(SystemExit):
            create(rig)
    assert counts(rig) == (0, 0, 0, 0)
    with sqlite3.connect(rig.path) as db:
        assert db.execute("SELECT COUNT(*) FROM charters").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    with pytest.raises(c.ReviewRefused):
        reopen(rig).prepare("0" * 64, target={"providerInstanceId": "provider", "model": "model"}, capabilities=capabilities())


def test_unbound_or_altered_charter_refuses_replay(rig):
    req, _, _, package = ready(rig)
    assert rig.intake(req.binding, package).usable_vote
    with sqlite3.connect(rig.path) as db:
        db.execute("UPDATE charters SET raw=?", (b"{}",))
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        reopen(rig).resume(req.binding)


def test_correction_permission_is_frozen_and_injection_cannot_expand(rig):
    charter = {"schema": "t3_host_charter.v1", "review_brief": "No correction", "host_scope": rig.host_scope}
    req = create(rig, charter=charter)
    status = registration(rig, req, prepare(rig, req))
    rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
    with pytest.raises(c.ReviewRefused, match="result_unavailable"):
        reopen(rig).correction(req.binding, capabilities=capabilities())
    class Expanded(g.T3NonGatingPolicy):
        def authorize(self, context):
            return replace(super().authorize(context), correction_allowed=True)
    expanded = g.T3ReviewService(rig.directory, host_scope=rig.host_scope, policy=Expanded(rig.charter))
    with pytest.raises(c.ReviewRefused, match="binding_mismatch"):
        create(expanded, coordinator_key="expanded", charter=charter)
    assert counts(rig)[0] == 1


@pytest.mark.parametrize("gate", ["identity", "complete_recovery", "gateway", "reservation"])
def test_matching_bypass_mutations(rig, monkeypatch, gate):
    req, _, status, good = ready(rig)
    if gate in ("identity", "complete_recovery"):
        bad = deepcopy(good)
        if gate == "identity":
            bad["completion"]["result"]["childRunId"] = "other"
        else:
            bad["timeline"][0]["result"].update(hasMore=True, nextPosition=7)
        no_delivery(rig, req, bad)
        unrelated = deepcopy(good)
        if gate == "identity":
            monkeypatch.setattr(t, "recover", skip_completion_run_comparison())
            unrelated["timeline"][0]["result"].update(hasMore=True, nextPosition=7)
        else:
            recover = t.recover
            def skip_traversal(binding, identity, scope, package):
                candidate = deepcopy(package)
                # Falsify only coverage: leave text/identity/status untouched.
                candidate["timeline"] = candidate["timeline"][:1]
                candidate["timeline"][0]["result"]["hasMore"] = False
                return recover(binding, identity, scope, candidate)
            monkeypatch.setattr(t, "recover", skip_traversal)
            unrelated["completion"]["result"]["childRunId"] = "other"
        no_delivery(rig, req, unrelated)
        sent, received = observe_worker(monkeypatch)
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            no_delivery(rig, req, bad)
        assert len(sent) == len(received) == 1
        history = rig.coordinator.validation_history(req.binding)
        assert history[-1]["invocation"]["ipc_id"] == received[0]["id"] == sent[0][0]
        assert sent[0][2].encode() == raw(payload(req))
    elif gate == "gateway":
        sent, received = observe_worker(monkeypatch)
        record = rig.intake(req.binding, good)
        assert_real_parse(record, sent, received, raw(payload(req)), b.snapshot_baml_sources(), rig.coordinator.private_body(record.record_id))
        sent.clear()
        received.clear()
        monkeypatch.setattr(rig.coordinator, "ingest", lambda *a, **kw: record)
        monkeypatch.setattr(rig.coordinator, "revalidate", lambda *a, **kw: record)
        replay = rig.intake(req.binding, good)
        with pytest.raises(AssertionError, match="bypassed"):
            assert_real_parse(replay, sent, received, raw(payload(req)), b.snapshot_baml_sources(), payload(req))
    else:
        rig.intake(req.binding, delivery(rig, req, status, b"invalid"))
        reserve = rig.coordinator.reserve_correction
        calls = []
        def tracked(binding):
            calls.append(binding)
            return reserve(binding)
        with monkeypatch.context() as patch:
            patch.setattr(rig.coordinator, "reserve_correction", tracked)
            action = rig.correction(req.binding, capabilities=capabilities())
        assert calls == [req.binding]
        reserved = rig.coordinator.correction_request(req.binding)
        assert action.request_binding == reserved.binding and counts(rig)[0] == 2
        other = create(rig, coordinator_key="second")
        other_status = registration(rig, other, prepare(rig, other))
        rig.intake(other.binding, delivery(rig, other, other_status, b"invalid"))
        # A cached object is not a durable reservation for this lineage.
        monkeypatch.setattr(rig.coordinator, "reserve_correction", lambda binding: reserved)
        rig.correction(other.binding, capabilities=capabilities())
        with pytest.raises(AssertionError):
            assert rig.coordinator.correction_request(other.binding) is not None


VECTORS = json.loads((Path(__file__).parent / "data/typed_review_contract_vectors.json").read_text())["lineage"]


@pytest.mark.parametrize("scenario", VECTORS["scenarios"], ids=lambda s: s["name"])
def test_frozen_lineage_replay_through_adapter(rig, scenario):
    """Transport replaces the fixture envelope, never its body or expectations.

    reserve/recover retain their distinct frozen coordinator semantics. Service
    correction both reserves and resumes, so a repeated *reserve* tests the
    public coordinator reservation API, whereas recovery also exercises resume.
    """
    assert VECTORS["schema"] == "typed_review_lineage_replay.v1"
    service, saved, actions, statuses, trace = rig, {}, {}, {}, []
    def resolve(value):
        if isinstance(value, str) and value.startswith("$"):
            name, field = value[1:].split(".")
            obj = saved[name]
            return getattr(obj, field) if hasattr(obj, field) else obj.value[field]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value
    for index, step in enumerate(scenario["steps"]):
        inputs, expected = resolve(step["inputs"]), resolve(step["expect"])
        op, result, refused = step["op"], None, None
        try:
            if op == "create":
                charter = {"schema": "t3_host_charter.v1", "review_brief": inputs.pop("brief_utf8"),
                           "host_scope": service.host_scope, "allow_correction": True}
                result = service.request(charter=charter, source_snapshot=b.snapshot_baml_sources(), **inputs)
                if result.binding not in actions:
                    actions[result.binding] = prepare(service, result)
            elif op == "ingest":
                req = service.coordinator.load_request(inputs["binding"])
                if req.binding not in statuses:
                    statuses[req.binding] = registration(service, req, actions[req.binding])
                body = json.dumps(inputs["body_json"], separators=(",", ":"), ensure_ascii=False).encode() + b" " * inputs.get("body_suffix_spaces", 0)
                package = delivery(service, req, statuses[req.binding], body)
                package["evidence_digests"] = inputs["evidence_digests"]
                (service.directory / f"vector-{index}-source.json").write_bytes(t.relay_json(package))
                result = service.intake(req.binding, package)
            elif op == "reserve":
                prior = service.coordinator.correction_request(inputs["binding"])
                if prior is not None:
                    result = service.coordinator.reserve_correction(inputs["binding"])
                else:
                    action = service.correction(inputs["binding"], capabilities=capabilities())
                    result = service.coordinator.correction_request(inputs["binding"])
                    actions[result.binding] = action
            elif op == "recover":
                result = service.coordinator.correction_request(inputs["binding"])
                replay = service.resume(result.binding)
                assert (isinstance(replay, t.HostAction) and replay.kind == "unresolved") or isinstance(replay, c.ContentRecord)
            elif op == "restart":
                service = reopen(service)
            else:
                assert op == "revalidate"
                result = service.resume(inputs["binding"])
        except c.ReviewRefused as exc:
            refused = exc.code
        trace.append({"step": index, "op": op, "refused": refused,
                      "record_id": getattr(result, "record_id", None), "expected": expected})
        (service.directory / "vector-trace.json").write_text(json.dumps(trace, indent=2))
        assert refused == expected.get("refused"), trace[-1]
        if refused is None:
            for field, value in expected.items():
                different = field.endswith("_not")
                field = field[:-4] if different else field
                actual = getattr(result, field) if hasattr(result, field) else result.value[field]
                assert (actual != value) if different else (actual == value), trace[-1]
            if "save" in step:
                saved[step["save"]] = result
        with sqlite3.connect(service.coordinator.path) as db:
            standing = db.execute("SELECT standing FROM lineages WHERE id=?", (saved["original"].lineage_id,)).fetchone()[0]
            assert standing == resolve(step["standing"]), trace[-1]
            assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
