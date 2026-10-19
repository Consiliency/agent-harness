"""SL-1 conformance: valid controls always consume real pinned worker replies.

TestPolicy is a fake *existing host policy*, never a production admission issuer.
Monkeypatched worker successes are used only for negative mutation controls.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

import pytest

from phase_loop_runtime import baml_modular as b
from phase_loop_runtime import review_contract as c


class TestPolicy:
    __test__ = False
    identity = "a" * 64

    def __init__(self, governed=False, deferred=False, trust=True):
        self.governed, self.deferred, self.trust = governed, deferred, trust

    def authorize(self, context):
        return c.Admission("GOVERNED" if self.governed else "NON_GATING",
                           ("HOST_ATTESTED", "TRANSPORT_CAPTURED"), True, governed_provenance=("TRANSPORT_CAPTURED",) if self.governed else ())

    def admit_transport(self, request, registration):
        return self.trust and registration["host_identity"] == "test-coordinator"

    def allow_deferred(self, request, finding_key):
        return self.deferred


@pytest.fixture(scope="module", autouse=True)
def real_worker():
    b._reset_worker_for_tests(test_mode=True, deadline_s=30, retries=0)
    yield
    b._reset_worker_for_tests()


@pytest.fixture
def source():
    return b.snapshot_baml_sources()


@pytest.fixture
def gateway(tmp_path):
    return c.ReviewCoordinator(tmp_path / "private", policy=TestPolicy())


def request(gateway, source, **kw):
    key = kw.pop("coordinator_key", None) or uuid.uuid4().hex
    return gateway.create_request(
        coordinator_key=key,
        brief=b"Inspect the frozen contract", subjects=[{"kind": "document", "sha256": "b" * 64,
            "paths": ["contract.md"], "revision": None}], seat=kw.pop("seat", "seat-A"),
        source_snapshot=source, **kw)


def register(gateway, req, provenance="HOST_ATTESTED"):
    return gateway.register_transport(req.binding, host_identity="test-coordinator", provenance=provenance,
        identity={"taskId": "task-" + req.attempt_id, "childThreadId": "thread-1", "childRunId": "run-1"})


def finding(id="F1", blocking=False, **kw):
    return {"id": id, "severity": "BLOCKING" if blocking else "NON_BLOCKING", "title": "A concern",
            "explanation": "Reasoned from the supplied contract", "requested_change": "Clarify the condition",
            "obligation_refs": ["contract invariant"] if blocking else [], "evidence": [], "falsifier": None, **kw}


def payload(req, **kw):
    r = req.value
    value = {"schema_version": "review_reply.v1", "request_binding": req.binding,
             "review_status": "COMPLETE", "summary": "Inspected café 🐈", "limitations": []}
    if r["function"] == "EmitReviewDecision":
        value.update(schema_version="review_decision.v1", decision="ACCEPT", dispositions=[
            {"finding_key": e["key"], "status": "RESOLVED", "rationale": "Observed repair", "evidence": []}
            for e in r["ledger"]["entries"]])
    else:
        value.update(verdict=None if r["purpose"] == "advisory" else "AGREE", scope_reviewed=["frozen contract"],
                     findings=[], coverage=[{"question_id": q["id"], "status": "ANSWERED", "answer": "Inspected",
                                             "finding_ids": []} for q in r["questions"]])
    return {**value, **kw}


def raw(value):
    return ("\n  " + json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def ingest(gateway, req, value=None, **kw):
    register(gateway, req)
    body = raw(payload(req) if value is None else value)
    return gateway.ingest(req.binding, body=body, transport=body, **kw)


def assert_refused(code, call):
    with pytest.raises(c.ReviewRefused) as caught:
        call()
    assert str(caught.value) == code
    assert caught.value.__cause__ is None


def observe_worker(monkeypatch):
    sent, received = [], []
    send, receive = b._Client._send_op, b._Client._on_frame

    def record_send(self, gen, req):
        send(self, gen, req)
        if req.op.startswith("parse_review"):
            sent.append((gen.pending_id, req.op, json.loads(req.body)["raw"], req.fp))

    def record_receive(self, gen, line):
        frame = json.loads(line)
        if frame.get("operation", "").startswith("parse_review"):
            received.append(frame)
        receive(self, gen, line)

    monkeypatch.setattr(b._Client, "_send_op", record_send)
    monkeypatch.setattr(b._Client, "_on_frame", record_receive)
    return sent, received


def assert_real_parse(record, sent, received, original, source, private):
    assert len(sent) == len(received) == 1, "acceptance bypassed the actual worker invocation"
    rid, op, text, fp = sent[0]
    frame = received[0]
    assert text.encode() == original
    assert record.ipc_id == frame["id"] == rid
    assert record.operation == frame["operation"] == op
    assert record.contract_fingerprint == frame["fingerprint"] == fp == source.fingerprint
    assert record.runtime_version == frame["runtime_version"] == "0.20.1"
    assert c.strict_tree_equal(private, json.loads(frame["ok"]))
    assert record.parsed_digest == hashlib.sha256(c.canonical_json(json.loads(frame["ok"]))).hexdigest()


@pytest.mark.parametrize("function", ["EmitReviewReply", "EmitReviewDecision"])
def test_acceptance_observes_and_consumes_real_worker(gateway, source, monkeypatch, function):
    kw = {"function": function}
    if function == "EmitReviewDecision":
        seat = request(gateway, source)
        assert ingest(gateway, seat, payload(seat, verdict="DISAGREE", findings=[finding(blocking=True)])).usable
        kw["ledger"] = gateway.build_ledger([seat.lineage_id])
    req = request(gateway, source, **kw)
    sent, received = observe_worker(monkeypatch)
    value = payload(req)
    result = ingest(gateway, req, value)
    assert result.content_valid and result.usable and not result.governed_eligible
    assert_real_parse(result, sent, received, raw(value), source, gateway.private_body(result.record_id))
    print(json.dumps({"function": function, "operation": result.operation, "ipc_id": result.ipc_id,
                      "fingerprint": result.contract_fingerprint, "runtime_version": result.runtime_version,
                      "raw_digest": result.body_digest, "parsed_digest": result.parsed_digest}))
    built = gateway.build_request(req.binding)
    assert req._json in built.prompt
    assert "request_binding" in built.prompt
    assert req.binding in built.prompt and "Inspect the frozen contract" in built.prompt


def test_echo_invocation_bypass_is_detected_by_recording_control(gateway, source, monkeypatch):
    req = request(gateway, source)
    value = payload(req)
    sent, received = observe_worker(monkeypatch)
    # Deliberately malicious implementation mutation. Tree equality alone passes.
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **k: b.ReviewParseResult(
        "EmitReviewReply", "parse_review_reply", 99, source.fingerprint, "0.20.1", value))
    result = ingest(gateway, req, value)
    with pytest.raises(AssertionError, match="bypassed"):
        assert_real_parse(result, sent, received, raw(value), source, value)


def test_class_schema_only_bypass_cannot_accept(gateway, source, monkeypatch):
    req = request(gateway, source)
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **k: payload(req))
    assert ingest(gateway, req).rejection_code == "baml_unavailable"


def test_mutated_actual_worker_reply_is_rejected(gateway, source, monkeypatch):
    req = request(gateway, source)
    receive = b._Client._on_frame
    seen = []

    def mutate(self, gen, line):
        frame = json.loads(line)
        if frame.get("operation") == "parse_review_reply":
            seen.append(frame["id"])
            value = json.loads(frame["ok"])
            value["summary"] = "changed by negative control"
            frame["ok"] = json.dumps(value)
            line = json.dumps(frame)
        receive(self, gen, line)

    monkeypatch.setattr(b._Client, "_on_frame", mutate)
    result = ingest(gateway, req)
    assert len(seen) == 1 and result.rejection_code == "baml_changed_value" and not result.content_valid


@pytest.mark.parametrize("field,value", [("operation", "parse_closeout"), ("function_name", "ReviewReplyV1"),
    ("request_id", True), ("request_id", 0), ("fingerprint", "f" * 64), ("runtime_version", "other")])
def test_metadata_mutations_refuse(gateway, source, monkeypatch, field, value):
    req = request(gateway, source)
    parse = b.parse_review_response
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **k: replace(parse(*a, **k), **{field: value}))
    result = ingest(gateway, req)
    assert result.rejection_code == "baml_unavailable" and not result.content_valid


@pytest.mark.parametrize("body", [b"{}{}", b"{} AGREE", b"{} RECOMMENDATION", b"{} FORCING DECISION",
    b"prose {}", b"```json\n{}\n```", b'{"a":1,"a":2}', b'{"a":{"x":1,"x":2}}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'{"x":', b"[]", b"null", b"\xff",
    b'{"x":"\\ud800"}', b'{"\\udfff":1}', b"\xef\xbb\xbf{}"])
def test_original_json_negatives_never_call_worker(gateway, source, monkeypatch, body):
    req = request(gateway, source)
    register(gateway, req)
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **k: pytest.fail("precheck bypass"))
    result = gateway.ingest(req.binding, body=body, transport=body)
    assert result.rejection_code == "invalid_json"


@pytest.mark.parametrize("mutator", [lambda v: v.pop("verdict"), lambda v: v.update(verified=True),
    lambda v: v.update(findings=None), lambda v: v.update(summary=4), lambda v: v.update(verdict="agree"),
    lambda v: v.update(scope_reviewed="contract"), lambda v: v.update(review_status=True)])
def test_baml_derived_strict_schema_negatives(gateway, source, monkeypatch, mutator):
    req = request(gateway, source)
    value = payload(req)
    mutator(value)
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **k: pytest.fail("precheck bypass"))
    assert ingest(gateway, req, value).rejection_code == "schema_mismatch"


@pytest.mark.parametrize("mutator,code", [
    (lambda v: v.update(request_binding="0" * 64), "binding_mismatch"),
    (lambda v: v.update(schema_version="review_reply.v2"), "semantic_mismatch"),
    (lambda v: v.update(summary="  "), "semantic_mismatch"),
    (lambda v: v.update(verdict=None), "semantic_mismatch"),
    (lambda v: v.update(scope_reviewed=[]), "semantic_mismatch"),
    (lambda v: v.update(verdict="DISAGREE"), "semantic_mismatch"),
    (lambda v: v.update(verdict="PARTIALLY_AGREE"), "semantic_mismatch"),
    (lambda v: v.update(findings=[finding(blocking=True)]), "semantic_mismatch"),
    (lambda v: v.update(findings=[finding(), finding()]), "semantic_mismatch"),
    (lambda v: v.update(verdict="DISAGREE", findings=[finding(blocking=True, obligation_refs=[])]), "semantic_mismatch"),
    (lambda v: v.update(findings=[finding(falsifier={"nodeid": "", "diff": ""})]), "semantic_mismatch"),
    (lambda v: v.update(review_status="INCOMPLETE", verdict=None), "semantic_mismatch"),
    (lambda v: v.update(review_status="INCOMPLETE", limitations=["missing input"]), "semantic_mismatch"),
    (lambda v: v.update(coverage=[{"question_id": "foreign", "status": "ANSWERED", "answer": "yes", "finding_ids": []}]), "semantic_mismatch"),
])
def test_semantic_negatives(gateway, source, mutator, code):
    req = request(gateway, source)
    value = payload(req)
    mutator(value)
    result = ingest(gateway, req, value)
    assert result.ipc_id is not None  # real parse precedes semantic rejection
    assert result.rejection_code == code and not result.content_valid


@pytest.mark.parametrize("purpose,verdict,findings", [("review", "AGREE", []),
    ("review", "DISAGREE", [finding(blocking=True)]),
    ("review", "PARTIALLY_AGREE", [finding()]),
    ("advisory", None, [finding()])])
def test_lens_free_valid_review_advisory_and_dissent(gateway, source, purpose, verdict, findings):
    req = request(gateway, source, purpose=purpose)
    result = ingest(gateway, req, payload(req, verdict=verdict, findings=findings))
    assert result.usable and not result.governed_eligible
    assert result.usable_vote == (purpose == "review") and not result.usable_ruling
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))


@pytest.mark.parametrize("verdict,findings", [("AGREE", []), (None, [finding(blocking=True)])])
def test_advisory_cannot_claim_verdict_or_defect(gateway, source, verdict, findings):
    req = request(gateway, source, purpose="advisory", lens="An arbitrary open-ended lens")
    assert ingest(gateway, req, payload(req, verdict=verdict, findings=findings)).rejection_code == "semantic_mismatch"


def test_incomplete_retains_findings_without_vote(gateway, source):
    req = request(gateway, source)
    result = ingest(gateway, req, payload(req, verdict=None, review_status="INCOMPLETE",
        findings=[finding(blocking=True)], limitations=["not enough material"]))
    assert result.content_valid and not result.usable and result.rejection_code == "result_incomplete"
    ledger = gateway.build_ledger([req.lineage_id])
    assert [e["kind"] for e in ledger["entries"]] == ["finding", "status"]
    assert ledger["entries"][0]["body"]["id"] == "F1"


def test_n9_structurally_invalid_blocking_falsifier_is_private_content(gateway, source):
    req = request(gateway, source)
    f = finding(id="../not-a-valid-gate-id", blocking=True, falsifier={"nodeid": "", "diff": "not a patch"})
    result = ingest(gateway, req, payload(req, verdict="PARTIALLY_AGREE", findings=[f]))
    assert result.content_valid and result.usable
    assert gateway.private_body(result.record_id)["findings"][0] == f


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "finding", "not_assessed", "blank"])
def test_coverage_exact_membership(gateway, source, mutation):
    req = request(gateway, source, questions=[{"id": "Q1", "text": "Does it bind?"}])
    value = payload(req)
    if mutation == "missing":
        value["coverage"] = []
    elif mutation == "duplicate":
        value["coverage"] *= 2
    elif mutation == "foreign":
        value["coverage"][0]["question_id"] = "Q2"
    elif mutation == "finding":
        value["coverage"][0]["finding_ids"] = ["F1"]
    elif mutation == "not_assessed":
        value["coverage"][0]["status"] = "NOT_ASSESSED"
    else:
        value["coverage"][0]["answer"] = " "
    assert ingest(gateway, req, value).rejection_code == "semantic_mismatch"


def test_evidence_membership_digest_and_unverified_no_fetch(gateway, source):
    def run(observed):
        req = request(gateway, source, evidence=[{"handle": "E1", "sha256": "c" * 64}])
        f = finding(evidence=[{"basis": "OBSERVED", "description": "test execution", "reference": "E1"},
                              {"basis": "SUPPLIED", "description": "untrusted source", "reference": "https://never-fetch.invalid"},
                              {"basis": "REASONED", "description": "reasoning", "reference": None}])
        return ingest(gateway, req, payload(req, verdict="PARTIALLY_AGREE", findings=[f]), evidence_digests=observed)
    assert run({"E1": "c" * 64}).unverified_evidence_count == 2
    assert run({}).unverified_evidence_count == 3
    assert_refused("binding_mismatch", lambda: run({"E1": "d" * 64}))
    assert_refused("binding_mismatch", lambda: run({"foreign": "c" * 64}))


def test_unicode_bytes_depth_and_text_boundaries():
    prefix = b'{"x":"'
    body = prefix + b"a" * (c.MAX_BYTES - len(prefix) - 2) + b'"}'
    # Diff alone is exempt from the field cap, never from bytes.
    prefix = b'{"falsifier":{"diff":"'
    body = prefix + b"a" * (c.MAX_BYTES - len(prefix) - 3) + b'"}}'
    assert len(body) == c.MAX_BYTES
    assert c.decode_original(body)[1]["falsifier"]["diff"]
    assert_refused("limit_exceeded", lambda: c.decode_original(body + b" "))
    for count, accepted in [(32, True), (33, False)]:
        nested = b'{"x":' * count + b"null" + b"}" * count
        if accepted:
            c.decode_original(nested)
        else:
            assert_refused("limit_exceeded", lambda: c.decode_original(nested))
    for count in [c.MAX_TEXT, c.MAX_TEXT + 1]:
        encoded = raw({"x": "🐈" * count})
        if count == c.MAX_TEXT:
            assert len(c.decode_original(encoded)[1]["x"]) == c.MAX_TEXT
        else:
            assert_refused("limit_exceeded", lambda: c.decode_original(encoded))
    assert c.decode_original(b'{"x":"\\ud83d\\udc08"}')[1]["x"] == "🐈"


@pytest.mark.parametrize("kind,limit", [("findings", 200), ("evidence", 100), ("questions", 200)])
def test_list_limits_at_boundary_and_beyond(gateway, source, kind, limit):
    for n in (limit, limit + 1):
        if kind == "questions":
            questions = [{"id": str(i), "text": "Inspect"} for i in range(n)]
            if n > limit:
                assert_refused("limit_exceeded", lambda: request(gateway, source, questions=questions))
                continue
            req = request(gateway, source, questions=questions)
            value = payload(req)
        else:
            req = request(gateway, source)
            findings = [finding(str(i)) for i in range(n)] if kind == "findings" else [finding(evidence=[
                {"basis": "REASONED", "description": "reason", "reference": None} for _ in range(n)])]
            value = payload(req, verdict="PARTIALLY_AGREE", findings=findings)
        result = ingest(gateway, req, value)
        assert result.usable if n == limit else result.rejection_code == "limit_exceeded"


def test_text_and_diff_limits_at_acceptance_constructor(gateway, source):
    req = request(gateway, source)
    assert ingest(gateway, req, payload(req, summary="🐈" * c.MAX_TEXT)).usable
    req = request(gateway, source)
    assert ingest(gateway, req, payload(req, summary="🐈" * (c.MAX_TEXT + 1))).rejection_code == "limit_exceeded"
    req = request(gateway, source)
    assert ingest(gateway, req, payload(req, verdict="DISAGREE", findings=[finding(blocking=True,
        falsifier={"nodeid": "not-a-node", "diff": "x" * 25_000})])).usable
    req = request(gateway, source, byte_limit=100)
    result = ingest(gateway, req)
    assert result.rejection_code == "limit_exceeded" and result.outcome == "invalid_content"
    assert not result.content_valid and result.ipc_id is None


def test_strict_tree_equality():
    assert not c.strict_tree_equal({"a": True}, {"a": 1})
    assert not c.strict_tree_equal({"a": 1}, {"a": 1.0})
    assert not c.strict_tree_equal({"a": None}, {})
    assert not c.strict_tree_equal({"a": [1, 2]}, {"a": [2, 1]})
    assert c.strict_tree_equal({"a": 1, "b": None}, {"b": None, "a": 1})


def test_frozen_request_input_identity(gateway, source):
    subjects = [{"kind": "snapshot", "sha256": "b" * 64, "paths": ["dirty.py"], "revision": None}]
    questions = [{"id": "Q1", "text": "inspect"}]
    req = gateway.create_request(coordinator_key="round-A/seat-A", brief=b"brief", subjects=subjects, seat="A", questions=questions, source_snapshot=source)
    binding = req.binding
    subjects[0]["paths"].append("other.py")
    questions[0]["text"] = "changed"
    req.value["seat"] = "changed"
    assert req.binding == binding
    for key, value in [("seat", "B"), ("brief_digest", "0" * 64), ("lens", "lens"),
                       ("purpose", "advisory"), ("byte_limit", 100), ("contract_fingerprint", "0" * 64)]:
        changed = {**req.value, key: value}
        assert c.canonical_digest("request", changed) != binding
    assert c.canonical_digest("request", ["a", "b"]) != c.canonical_digest("request", ["b", "a"])
    assert c.canonical_digest("request", "é") != c.canonical_digest("request", "e\u0301")


def test_bound_snapshot_mutates_strict_schema_only_for_that_snapshot(gateway, source):
    req = request(gateway, source)
    value = payload(req)
    files = dict(source.files)
    files["review_reply.baml"] = files["review_reply.baml"].replace("    summary: string,", "    note: string,").replace("    AGREE,", "    HISTORICAL_AGREE,")
    historical = b.snapshot_baml_sources(files)
    changed = {**value, "note": value["summary"], "verdict": "HISTORICAL_AGREE"}
    changed.pop("summary")
    c.strict_precheck(raw(value), source, "EmitReviewReply")
    c.strict_precheck(raw(changed), historical, "EmitReviewReply")
    assert_refused("schema_mismatch", lambda: c.strict_precheck(raw(changed), source, "EmitReviewReply"))
    assert_refused("schema_mismatch", lambda: c.strict_precheck(raw(value), historical, "EmitReviewReply"))
    assert b.snapshot_baml_sources().fingerprint == source.fingerprint


def test_historical_replay_never_reads_current_sources(gateway, source, monkeypatch):
    req = request(gateway, source)
    first = ingest(gateway, req)
    assert first.content_valid
    def forbidden(*a, **k):
        pytest.fail("historical replay read current sources/cache")
    monkeypatch.setattr(b, "_snapshot_files", forbidden)
    monkeypatch.setattr(b, "_enum_literal_map", forbidden)
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    result = reopened.revalidate(req.binding)
    assert result.content_valid and result.contract_fingerprint == source.fingerprint
    assert reopened.private_body(result.record_id) == gateway.private_body(first.record_id)


@pytest.mark.parametrize("mutation", ["missing", "mismatch", "unsupported_runtime", "unsupported_contract", "unsupported_validator"])
def test_missing_mismatched_unsupported_saved_state_refuses(gateway, source, mutation):
    req = request(gateway, source)
    assert ingest(gateway, req).content_valid
    with sqlite3.connect(gateway.path) as db:
        if mutation == "missing":
            db.execute("DELETE FROM sources")
        elif mutation == "mismatch":
            files = dict(source.files)
            files["review_reply.baml"] += "\n// changed\n"
            db.execute("UPDATE sources SET files=?", (json.dumps(files),))
        else:
            changed = req.value
            changed[{"unsupported_runtime": "runtime_version", "unsupported_contract": "contract_version",
                     "unsupported_validator": "validator_version"}[mutation]] = "unsupported"
            altered = c.FrozenRequest(c.canonical_json(changed).decode())
            db.execute("UPDATE requests SET body=?, binding=?", (altered._json, altered.binding))
            req = altered
    if mutation.startswith("unsupported"):
        assert_refused("baml_unavailable", lambda: gateway.load_request(req.binding))
    else:
        assert gateway.revalidate(req.binding).rejection_code == "baml_unavailable"


def test_worker_outage_retains_bytes_then_local_revalidation(gateway, source, monkeypatch):
    req = request(gateway, source)
    with monkeypatch.context() as patch:
        def unavailable(*a, **k):
            raise b.BamlWorkerError("timeout", "PRIVATE-MODEL-STRING")
        patch.setattr(b, "parse_review_response", unavailable)
        first = ingest(gateway, req)
    assert first.rejection_code == "baml_unavailable" and not first.usable
    assert "PRIVATE-MODEL-STRING" not in repr(first)
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    result = reopened.revalidate(req.binding)
    assert result.content_valid and result.attempt_id == first.attempt_id
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 2


def test_real_worker_parse_failure_cannot_mint_valid_record(gateway, source, monkeypatch):
    req = request(gateway, source)
    parse = b.parse_review_response
    # Force real BAML to reject a string while retaining a schema-valid original.
    monkeypatch.setattr(b, "parse_review_response", lambda function, text, **kw: parse(function, "not JSON", **kw))
    result = ingest(gateway, req)
    assert result.rejection_code == "baml_parse_failed" and not result.content_valid


def test_delivery_idempotence_conflict_and_private_metadata(gateway, source):
    req = request(gateway, source, seat="PRIVATE-SEAT")
    value = payload(req, summary="PRIVATE-MODEL-SENTINEL")
    first = ingest(gateway, req, value)
    assert ingest(gateway, req, value) == first
    changed = raw({**value, "summary": "changed"})
    assert_refused("delivery_conflict", lambda: gateway.ingest(req.binding, body=changed, transport=changed))
    body = raw(value)
    assert_refused("delivery_conflict", lambda: gateway.ingest(req.binding, body=body, transport=b"changed envelope"))
    metadata = json.dumps(asdict(first))
    assert "PRIVATE" not in metadata and "test-coordinator" not in metadata
    assert "PRIVATE" not in repr(req)
    assert gateway.private_body(first.record_id)["summary"] == "PRIVATE-MODEL-SENTINEL"
    if os.name == "posix":
        assert os.stat(gateway.directory).st_mode & 0o777 == 0o700
        assert os.stat(gateway.path).st_mode & 0o777 == 0o600


def test_concurrent_delivery_is_one_record(gateway, source):
    req = request(gateway, source)
    register(gateway, req)
    body = raw(payload(req))
    def one(_):
        other = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
        return other.ingest(req.binding, body=body, transport=body)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(4)))
    assert len({r.record_id for r in results}) == 1
    assert results[0].content_valid


def test_correction_budget_survives_invalid_correction_and_restart(gateway, source):
    req = request(gateway, source)
    failed = ingest(gateway, req, payload(req, verdict="DISAGREE"))
    correction = gateway.reserve_correction(req.binding)
    assert correction.lineage_id == req.lineage_id and correction.attempt_id != req.attempt_id
    assert correction.value["replaces_record_id"] == failed.record_id
    assert gateway.correction_context(correction.binding)["original_body"] == raw(payload(req, verdict="DISAGREE"))
    second = ingest(gateway, correction, payload(correction, verdict="DISAGREE"))
    assert second.rejection_code == "semantic_mismatch"
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert reopened.correction_request(req.binding) == correction
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(req.binding))
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(correction.binding))
    # Public creation generates a new independent lineage; it cannot reuse one.
    assert "lineage_id" not in __import__("inspect").signature(gateway.create_request).parameters


def test_concurrent_process_reservations_and_unknown_launch_cannot_reset(gateway, source):
    req = request(gateway, source)
    ingest(gateway, req, payload(req, verdict="DISAGREE"))
    script = """
import json, sys
from pathlib import Path
from test_review_contract import TestPolicy
from phase_loop_runtime.review_contract import ReviewCoordinator, ReviewRefused
g = ReviewCoordinator(Path(sys.argv[1]), policy=TestPolicy())
try:
    print(g.reserve_correction(sys.argv[2]).binding)
except ReviewRefused as e:
    print(e.code)
"""
    procs = [subprocess.Popen([sys.executable, "-c", script, str(gateway.directory), req.binding],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              cwd=Path(__file__).resolve().parents[2]) for _ in range(3)]
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, err
        outputs.append(out.strip())
    assert outputs.count("result_unavailable") == 2
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert reopened.correction_request(req.binding).binding in outputs
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(req.binding))


def test_valid_correction_replaces_original_standing_once(gateway, source):
    req = request(gateway, source)
    failure = ingest(gateway, req, payload(req, verdict="DISAGREE"))
    correction = gateway.reserve_correction(req.binding)
    result = ingest(gateway, correction)
    assert result.usable and result.replaces_record_id == failure.record_id
    ledger = gateway.build_ledger([req.lineage_id])
    assert ledger["records"] == [result.record_id]
    assert gateway.revalidate(req.binding).rejection_code == failure.rejection_code
    assert gateway.build_ledger([req.lineage_id])["records"] == [result.record_id]


def test_policy_provenance_and_capture_are_independent(tmp_path, source):
    for governed in (False, True):
        gateway = c.ReviewCoordinator(tmp_path / str(governed), policy=TestPolicy(governed=governed))
        req = request(gateway, source)
        register(gateway, req, "TRANSPORT_CAPTURED")
        body = raw(payload(req))
        assert_refused("binding_mismatch", lambda: gateway.ingest(req.binding, body=body, transport=body))
        assert_refused("binding_mismatch", lambda: gateway.ingest(req.binding, body=body, transport=body, captured_body=b"different"))
        result = gateway.ingest(req.binding, body=body, transport=body, captured_body=body)
        assert result.governed_eligible is governed
        assert result.provenance == "TRANSPORT_CAPTURED"
        host_req = request(gateway, source)
        assert not ingest(gateway, host_req).governed_eligible
    gateway = c.ReviewCoordinator(tmp_path / "untrusted", policy=TestPolicy(trust=False))
    req = request(gateway, source)
    assert_refused("binding_mismatch", lambda: register(gateway, req))
    assert_refused("binding_mismatch", lambda: gateway.register_transport(req.binding,
        host_identity="test-coordinator", provenance="SELF_ATTESTED", identity={"taskId": "task"}))


def president_request(gateway, source, incomplete=False):
    lineages = []
    for seat in ("seat-A", "seat-B"):
        req = request(gateway, source, seat=seat)
        kw = {"verdict": "DISAGREE", "findings": [finding(blocking=True)]}
        if incomplete and seat == "seat-A":
            kw.update(verdict=None, review_status="INCOMPLETE", limitations=["missing input"])
        assert ingest(gateway, req, payload(req, **kw)).content_valid
        lineages.append(req.lineage_id)
    ledger = gateway.build_ledger(lineages)
    return request(gateway, source, function="EmitReviewDecision", ledger=ledger)


def test_president_global_ledger_and_incomplete_findings(gateway, source):
    req = president_request(gateway, source, incomplete=True)
    entries = req.value["ledger"]["entries"]
    assert len(entries) == 3 and len({e["key"] for e in entries}) == 3
    assert [e["body"]["id"] for e in entries if e["kind"] == "finding"] == ["F1", "F1"]
    assert ingest(gateway, req).usable


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "open", "deferred", "complete_null", "incomplete_decision", "incomplete_no_limit"])
def test_president_disposition_and_status_negatives(gateway, source, mutation):
    req = president_request(gateway, source)
    value = payload(req)
    if mutation == "missing":
        value["dispositions"].pop()
    elif mutation == "duplicate":
        value["dispositions"].append(value["dispositions"][0])
    elif mutation == "foreign":
        value["dispositions"][0]["finding_key"] = "foreign"
    elif mutation in ("open", "deferred"):
        value["dispositions"][0]["status"] = mutation.upper()
    elif mutation == "complete_null":
        value["decision"] = None
    elif mutation == "incomplete_decision":
        value.update(review_status="INCOMPLETE", limitations=["missing input"])
    else:
        value.update(review_status="INCOMPLETE", decision=None)
    assert ingest(gateway, req, value).rejection_code == "semantic_mismatch"


def test_president_revise_incomplete_and_existing_defer_policy(gateway, source):
    req = president_request(gateway, source)
    value = payload(req, decision="REVISE")
    value["dispositions"][0]["status"] = "OPEN"
    assert ingest(gateway, req, value).usable
    req = president_request(gateway, source)
    result = ingest(gateway, req, payload(req, review_status="INCOMPLETE", decision=None, limitations=["missing input"]))
    assert result.content_valid and not result.usable
    gateway.policy.deferred = True
    req = president_request(gateway, source)
    value = payload(req)
    value["dispositions"][0]["status"] = "DEFERRED"
    assert ingest(gateway, req, value).usable


def test_president_tampered_or_changed_ledger_refuses(gateway, source):
    req = president_request(gateway, source)
    ledger = req.value["ledger"]
    ledger["entries"].pop()
    assert_refused("binding_mismatch", lambda: request(gateway, source, function="EmitReviewDecision", ledger=ledger))
    # Genuine coordinator transition: an invalid seat receives its substantive correction.
    seat = request(gateway, source)
    ingest(gateway, seat, payload(seat, verdict="DISAGREE"))
    original = gateway.build_ledger([seat.lineage_id])
    req = request(gateway, source, function="EmitReviewDecision", ledger=original)
    ruling = ingest(gateway, req)
    assert ruling.usable_ruling
    correction = gateway.reserve_correction(seat.binding)
    assert ingest(gateway, correction).usable_vote
    stale = gateway.revalidate(req.binding)
    assert stale.rejection_code == "result_unavailable" and stale.outcome == "transport_failure"
    assert not stale.content_valid and not stale.usable_ruling
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT standing FROM lineages WHERE id=?", (req.lineage_id,)).fetchone()[0] == ruling.record_id
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))
    # Stale already at first delivery also cannot charge the reviewer a correction.
    req2 = request(gateway, source, function="EmitReviewDecision", ledger=gateway.build_ledger([correction.lineage_id]))
    with sqlite3.connect(gateway.path) as db:
        db.execute("UPDATE lineages SET standing=NULL WHERE id=?", (correction.lineage_id,))
    assert ingest(gateway, req2).rejection_code == "result_unavailable"
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req2.binding))


def test_canonical_vectors_and_negative_domains():
    vectors = json.loads((Path(__file__).parent / "data" / "typed_review_contract_vectors.json").read_text())
    for v in vectors["canonical"]:
        assert c.canonical_json(v["value"]).decode() == v["canonical_utf8"]
        assert c.canonical_digest(v["domain"], v["value"]) == v["sha256"]
        other = "receipt" if v["domain"] == "request" else "request"
        assert c.canonical_digest(other, v["value"]) != v["sha256"]
    assert vectors["lineage"]["schema"] == "typed_review_lineage_replay.v1"


@pytest.mark.parametrize("correction", [False, True])
def test_exact_byte_cap_at_production_constructor(gateway, source, correction):
    for extra in (0, 1):
        req = request(gateway, source)
        if correction:
            ingest(gateway, req, payload(req, verdict="DISAGREE"))
            req = gateway.reserve_correction(req.binding)
        value = payload(req, verdict="DISAGREE", findings=[finding(blocking=True, falsifier={"nodeid": "invalid", "diff": ""})])
        value["findings"][0]["falsifier"]["diff"] = "x" * (c.MAX_BYTES - len(raw(value)) + extra)
        body = raw(value)
        assert len(body) == c.MAX_BYTES + extra
        register(gateway, req)
        if extra:
            result = gateway.ingest(req.binding, body=body, transport=body)
            assert result.outcome == "invalid_content" and result.rejection_code == "limit_exceeded"
            assert not result.usable and result.ipc_id is None
        else:
            assert gateway.ingest(req.binding, body=body, transport=body).usable


def test_depth_exhaustion_at_production_constructor(gateway, source, monkeypatch):
    req = request(gateway, source)
    register(gateway, req)
    body = b'{"x":' * 33 + b"null" + b"}" * 33
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **kw: pytest.fail("unbounded parse"))
    assert gateway.ingest(req.binding, body=body, transport=body).rejection_code == "limit_exceeded"


def test_integer_schema_never_accepts_boolean_or_float(gateway, source):
    req = request(gateway, source)
    files = dict(source.files)
    files["review_reply.baml"] = files["review_reply.baml"].replace("    summary: string,", "    summary: string,\n    counter: int,")
    numeric = b.snapshot_baml_sources(files)
    c.strict_precheck(raw({**payload(req), "counter": 1}), numeric, "EmitReviewReply")
    for counter in (True, 1.0, "1"):
        assert_refused("schema_mismatch", lambda: c.strict_precheck(raw({**payload(req), "counter": counter}), numeric, "EmitReviewReply"))


def test_same_coordinator_key_recovers_original_not_new_budget(gateway, source):
    req = request(gateway, source, coordinator_key="board-1/round-1/seat-A")
    assert request(gateway, source, coordinator_key="board-1/round-1/seat-A") == req
    assert_refused("delivery_conflict", lambda: request(gateway, source, coordinator_key="board-1/round-1/seat-A", lens="changed"))
    ingest(gateway, req, payload(req, verdict="DISAGREE"))
    correction = gateway.reserve_correction(req.binding)
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert request(reopened, source, coordinator_key="board-1/round-1/seat-A") == req
    assert reopened.correction_request(req.binding) == correction
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(req.binding))
    context = reopened.correction_context(correction.binding)
    assert context["original_brief"] == b"Inspect the frozen contract"
    prompt = reopened.build_request(correction.binding).prompt
    assert "substantive_replacement" in prompt and "semantic_mismatch" in prompt


def test_concurrent_process_intake_and_conflicting_delivery(gateway, source):
    req = request(gateway, source)
    register(gateway, req)
    body = raw(payload(req))
    script = """
import sys
from pathlib import Path
from test_review_contract import TestPolicy
from phase_loop_runtime.review_contract import ReviewCoordinator, ReviewRefused
g = ReviewCoordinator(Path(sys.argv[1]), policy=TestPolicy())
body = bytes.fromhex(sys.argv[3])
try:
    record = g.ingest(sys.argv[2], body=body, transport=body)
    print(record.record_id if record.content_valid else record.rejection_code)
except ReviewRefused as e:
    print(e.code)
"""
    procs = [subprocess.Popen([sys.executable, "-c", script, str(gateway.directory), req.binding, candidate.hex()],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[2])
        for candidate in (body, body, raw(payload(req, summary="conflicting")))]
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=45)
        assert proc.returncode == 0, err
        outputs.append(out.strip())
    assert outputs.count("delivery_conflict") in (1, 2)
    assert len({o for o in outputs if o != "delivery_conflict"}) == 1
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 1


def test_pending_intake_bytes_survive_crash_before_parse(gateway, source, monkeypatch):
    req = request(gateway, source)
    register(gateway, req)
    body = raw(payload(req))
    with monkeypatch.context() as patch:
        def crash(*a, **kw):
            raise SystemExit(23)
        patch.setattr(gateway, "_validate", crash)
        with pytest.raises(SystemExit):
            gateway.ingest(req.binding, body=body, transport=body)
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    result = reopened.ingest(req.binding, body=body, transport=body)
    assert result.content_valid and result.body_digest == hashlib.sha256(body).hexdigest()


def test_policy_change_and_registration_replacement_refuse(gateway, source):
    req = request(gateway, source)
    register(gateway, req)
    assert_refused("delivery_conflict", lambda: gateway.register_transport(req.binding,
        host_identity="test-coordinator", provenance="HOST_ATTESTED", identity={"taskId": "replacement"}))
    gateway.policy.identity = "b" * 64
    assert_refused("binding_mismatch", lambda: gateway.revalidate(req.binding))


def test_source_mismatch_does_not_reuse_idempotent_vote(gateway, source):
    req = request(gateway, source)
    assert ingest(gateway, req).usable
    with sqlite3.connect(gateway.path) as db:
        db.execute("DELETE FROM sources")
    assert_refused("baml_unavailable", lambda: ingest(gateway, req))


def test_full_request_vector_matches_real_constructor(gateway, source, monkeypatch):
    from types import SimpleNamespace
    vectors = json.loads((Path(__file__).parent / "data" / "typed_review_contract_vectors.json").read_text())
    expected = vectors["canonical"][0]["value"]
    ids = iter([SimpleNamespace(hex=x * 32) for x in "123"])
    monkeypatch.setattr(c.uuid, "uuid4", lambda: next(ids))
    req = request(gateway, source, coordinator_key="canonical-round/seat-A",
        questions=[{"id": "Q1", "text": "Inspect café 🐈"}], evidence=[{"handle": "E1", "sha256": "c" * 64}])
    # Source fingerprint is a pinned vector input, not a pin on future package outputs.
    assert {**req.value, "contract_fingerprint": expected["contract_fingerprint"]} == expected


def test_carried_dissent_requires_explicit_coordinator_delta_record(gateway, source):
    old = request(gateway, source, seat="old-seat")
    old_record = ingest(gateway, old, payload(old, verdict="DISAGREE", findings=[finding(blocking=True)]))
    current = request(gateway, source, seat="current-seat")
    assert ingest(gateway, current).usable
    assert_refused("binding_mismatch", lambda: gateway.build_ledger([current.lineage_id], carry_ids=[old_record.record_id]))
    carry = gateway.register_carry(old_record.record_id, reviewed_delta_digest="d" * 64, current_applicability_digest="e" * 64)
    ledger = gateway.build_ledger([current.lineage_id], carry_ids=[carry])
    assert ledger["carry_records"][0]["old_request_binding"] == old.binding
    assert ledger["entries"][0]["body"]["id"] == "F1"
    req = request(gateway, source, function="EmitReviewDecision", ledger=ledger)
    assert req.value["ledger_digest"] == c.canonical_digest("ledger", ledger)
    assert ingest(gateway, req).usable_ruling


def test_actual_historical_map_with_extra_declared_field_survives_package_change(gateway, source, monkeypatch):
    files = dict(source.files)
    files["review_reply.baml"] = files["review_reply.baml"].replace("    summary: string,", "    summary: string,\n    retained_note: string,")
    historical = b.snapshot_baml_sources(files)
    req = request(gateway, historical)
    value = payload(req, retained_note="Source-defined historical field")
    first = ingest(gateway, req, value)
    assert first.content_valid and first.contract_fingerprint == historical.fingerprint
    assert gateway.private_body(first.record_id)["retained_note"] == value["retained_note"]
    assert_refused("schema_mismatch", lambda: c.strict_precheck(raw(value), source, "EmitReviewReply"))
    # Current rendered map is now different; saved historical replay must ignore it.
    monkeypatch.setattr(b, "_snapshot_files", lambda: dict(source.files))
    assert gateway.revalidate(req.binding).content_valid
    current = request(gateway, source)
    assert ingest(gateway, current).content_valid


def test_required_nulls_and_nested_unknown_fields(gateway, source):
    for mutation in ("falsifier", "reference", "nested_unknown"):
        req = request(gateway, source)
        f = finding(evidence=[{"basis": "REASONED", "description": "reason", "reference": None}])
        if mutation == "falsifier":
            f.pop("falsifier")
        elif mutation == "reference":
            f["evidence"][0].pop("reference")
        else:
            f["evidence"][0]["verified"] = True
        assert ingest(gateway, req, payload(req, verdict="PARTIALLY_AGREE", findings=[f])).rejection_code == "schema_mismatch"


def test_model_strings_never_enter_rejected_record_or_exception(gateway, source):
    req = request(gateway, source)
    invalid = payload(req, summary="PRIVATE-CONTENT", verdict="PRIVATE-ENUM")
    result = ingest(gateway, req, invalid)
    assert result.rejection_code == "schema_mismatch" and "PRIVATE" not in repr(result)
    assert_refused("delivery_conflict", lambda: gateway.ingest(req.binding, body=b"PRIVATE-OTHER", transport=b"PRIVATE-ENVELOPE"))


def test_explicit_source_map_missing_declarations_cannot_accept(gateway, source):
    files = dict(source.files)
    files.pop("review_reply.baml")
    missing = b.snapshot_baml_sources(files)
    req = request(gateway, missing)
    result = ingest(gateway, req)
    assert result.rejection_code == "baml_unavailable" and not result.content_valid


@pytest.mark.parametrize("state", ["dissent", "incomplete", "invalid"])
def test_revalidation_stable_identity_and_durable_invocation_history(gateway, source, monkeypatch, state):
    seat = request(gateway, source)
    values = {
        "dissent": payload(seat, verdict="DISAGREE", findings=[finding(blocking=True)]),
        "incomplete": payload(seat, review_status="INCOMPLETE", verdict=None, limitations=["Unfinished"]),
        "invalid": payload(seat, verdict="DISAGREE"),
    }
    first = ingest(gateway, seat, values[state])
    assert first.outcome == {"dissent": "usable_review", "incomplete": "incomplete_review", "invalid": "invalid_content"}[state]
    ledger = gateway.build_ledger([seat.lineage_id])
    president = request(gateway, source, function="EmitReviewDecision", ledger=ledger)
    ruling = ingest(gateway, president)
    assert ruling.usable_ruling
    gateway = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    sent, received = observe_worker(monkeypatch)
    assert gateway.revalidate(seat.binding) == first
    assert gateway.build_ledger([seat.lineage_id]) == ledger
    assert gateway.revalidate(president.binding) == ruling
    assert len(sent) == len(received) == 2
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    for req, original, frame in ((seat, first, received[0]), (president, ruling, received[1])):
        history = reopened.validation_history(req.binding)
        assert len(history) == 2
        assert history[0]["result_record_id"] == history[1]["result_record_id"] == original.record_id
        actual = history[1]["invocation"]
        assert actual["ipc_id"] == frame["id"] != original.ipc_id
        assert actual["operation"] == frame["operation"]
        assert actual["contract_fingerprint"] == frame["fingerprint"]
        assert actual["runtime_version"] == frame["runtime_version"] == "0.20.1"
        assert actual["parsed_digest"] == original.parsed_digest
        assert actual["request_binding"] == req.binding
        print(json.dumps({"resume_state": state, "record_id": original.record_id,
            "original_ipc_id": original.ipc_id, "actual_invocation": actual}))
    # Idempotent delivery does not pretend to reparse or append an invocation.
    assert ingest(reopened, president) == ruling
    assert len(reopened.validation_history(president.binding)) == 2


def test_revalidation_outage_preserves_standing_but_blocks_current_use(gateway, source, monkeypatch):
    seat = request(gateway, source)
    first = ingest(gateway, seat, payload(seat, verdict="DISAGREE", findings=[finding(blocking=True)]))
    ledger = gateway.build_ledger([seat.lineage_id])
    president = request(gateway, source, function="EmitReviewDecision", ledger=ledger)
    ruling = ingest(gateway, president)
    with monkeypatch.context() as patch:
        def outage(*a, **kw):
            raise b.BamlWorkerError("timeout", "PRIVATE-OUTAGE")
        patch.setattr(b, "parse_review_response", outage)
        failure = gateway.revalidate(seat.binding)
    assert failure.rejection_code == "baml_unavailable" and not failure.usable
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT standing FROM lineages WHERE id=?", (seat.lineage_id,)).fetchone()[0] == first.record_id
    assert_refused("result_unavailable", lambda: gateway.build_ledger([seat.lineage_id]))
    stale = gateway.revalidate(president.binding)
    assert stale.rejection_code == "result_unavailable" and stale.outcome == "transport_failure"
    assert not stale.usable_ruling
    for req in (seat, president):
        assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert reopened.revalidate(seat.binding) == first
    assert reopened.build_ledger([seat.lineage_id]) == ledger
    assert reopened.revalidate(president.binding) == ruling
    assert [h["invocation"]["rejection_code"] for h in reopened.validation_history(seat.binding)] == [None, "baml_unavailable", None]
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM registrations").fetchone()[0] == 2


@pytest.mark.parametrize("observed", [["E1"], [], "PRIVATE-HOST", 0, False,
    {"E1": []}, {"E1": "PRIVATE-DIGEST"}, {"E1": "D" * 64}, {"E1": "d" * 64},
    {"foreign": "c" * 64}, {"": "c" * 64}, {1: "c" * 64}, {"\ud800": "c" * 64}])
def test_host_evidence_refusal_is_predelivery_and_retryable(gateway, source, monkeypatch, observed):
    req = request(gateway, source, evidence=[{"handle": "E1", "sha256": "c" * 64}])
    register(gateway, req)
    body = raw(payload(req))
    with monkeypatch.context() as patch:
        patch.setattr(b, "parse_review_response", lambda *a, **kw: pytest.fail("host refusal reached worker"))
        assert_refused("binding_mismatch", lambda: gateway.ingest(req.binding, body=body, transport=body, evidence_digests=observed))
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))
    assert gateway.ingest(req.binding, body=body, transport=body, evidence_digests={"E1": "c" * 64}).usable


def test_json_envelope_expansion_vectors_do_not_stall_reviewer_lineage(gateway, source):
    vectors = json.loads((Path(__file__).parent / "data" / "typed_review_contract_vectors.json").read_text())["transport_limits"]
    assert vectors["body_bytes"] == c.MAX_BYTES
    assert vectors["envelope_bytes"] == c.MAX_TRANSPORT_BYTES
    assert c.MAX_TRANSPORT_BYTES == vectors["json_escape_expansion"] * c.MAX_BYTES + vectors["framing_bytes"]
    for case in vectors["cases"]:
        req = request(gateway, source)
        register(gateway, req)
        text = case["character"] * case["repeat"]
        body = text.encode("utf-8")
        envelope = json.dumps({"body": text, "metadata": "m" * (vectors["framing_bytes"] - 128)},
                              ensure_ascii=True).encode("utf-8")
        assert len(body) <= c.MAX_BYTES
        assert 2 * c.MAX_BYTES < len(envelope) <= c.MAX_TRANSPORT_BYTES
        # These are invalid original JSON, not host errors: no accepted parse is fabricated.
        result = gateway.ingest(req.binding, body=body, transport=envelope)
        assert result.outcome == "invalid_content" and result.rejection_code == "invalid_json"
        assert result.ipc_id is None and not result.usable
        assert gateway.ingest(req.binding, body=body, transport=envelope) == result
        assert gateway.build_ledger([req.lineage_id])["entries"][0]["kind"] == "status"
        assert gateway.reserve_correction(req.binding).value["replaces_record_id"] == result.record_id


def test_host_envelope_storage_bound_and_reserved_lineage(gateway, source, monkeypatch):
    original = request(gateway, source)
    failed = ingest(gateway, original, payload(original, verdict="DISAGREE"))
    correction = gateway.reserve_correction(original.binding)
    register(gateway, correction)
    body = raw(payload(correction))
    envelope = b"PRIVATE-ENVELOPE" + b"x" * (c.MAX_TRANSPORT_BYTES + 1 - len(b"PRIVATE-ENVELOPE"))
    with monkeypatch.context() as patch:
        patch.setattr(b, "parse_review_response", lambda *a, **kw: pytest.fail("over-limit reached worker"))
        assert_refused("limit_exceeded", lambda: gateway.ingest(correction.binding, body=body, transport=envelope))
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM deliveries WHERE binding=?", (correction.binding,)).fetchone()[0] == 0
        observations = [json.loads(row[0]) for row in db.execute("SELECT metadata FROM intake_refusals")]
        assert observations == [{"request_binding": correction.binding, "rejection_code": "limit_exceeded",
            "body_digest": hashlib.sha256(body).hexdigest(), "transport_digest": hashlib.sha256(envelope).hexdigest(),
            "body_bytes": len(body), "transport_bytes": len(envelope)}]
    assert gateway.path.stat().st_size < 512_000
    assert b"PRIVATE-BODY" not in gateway.path.read_bytes() and b"PRIVATE-ENVELOPE" not in gateway.path.read_bytes()
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert reopened.correction_request(original.binding) == correction
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(original.binding))
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(correction.binding))
    corrected = raw(payload(correction))
    accepted = reopened.ingest(correction.binding, body=corrected, transport=b"x" * c.MAX_TRANSPORT_BYTES)
    assert accepted.usable and accepted.replaces_record_id == failed.record_id
    assert reopened.build_ledger([original.lineage_id])["records"] == [accepted.record_id]
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(original.binding))


@pytest.mark.parametrize("correction", [False, True])
@pytest.mark.parametrize("envelope_overflow", [False, True])
def test_oversized_body_is_terminal_digest_only(gateway, source, monkeypatch, correction, envelope_overflow):
    original = request(gateway, source, byte_limit=4096)
    prior = ingest(gateway, original, payload(original, verdict="DISAGREE")) if correction else None
    req = gateway.reserve_correction(original.binding) if correction else original
    register(gateway, req)
    body = b"PRIVATE-BODY" + b"x" * (4097 - len(b"PRIVATE-BODY"))
    envelope = b"PRIVATE-ENVELOPE" + b"x" * (c.MAX_TRANSPORT_BYTES if envelope_overflow else 0)
    sent, received = observe_worker(monkeypatch)
    result = gateway.ingest(req.binding, body=body, transport=envelope)
    assert result.outcome == "invalid_content" and result.rejection_code == "limit_exceeded"
    assert not result.content_valid and not result.usable and not result.governed_eligible
    assert result.body_digest == hashlib.sha256(body).hexdigest()
    assert result.transport_digest == hashlib.sha256(envelope).hexdigest()
    assert result.replaces_record_id == (prior.record_id if prior else None)
    for field in ("operation", "ipc_id", "runtime_version", "parsed_digest"):
        assert getattr(result, field) is None
    assert_refused("binding_mismatch", lambda: gateway.private_body(result.record_id))
    ledger = gateway.build_ledger([req.lineage_id])
    assert ledger["records"] == [result.record_id]
    assert ledger["entries"][0]["kind"] == "status"
    assert ledger["entries"][0]["body"] == {"outcome": "invalid_content", "rejection_code": "limit_exceeded"}
    with sqlite3.connect(gateway.path) as db:
        stored = db.execute("SELECT raw, transport, omitted FROM deliveries WHERE binding=?", (req.binding,)).fetchone()
        assert stored[:2] == (None, None)
        assert json.loads(stored[2]) == {"body_digest": result.body_digest, "transport_digest": result.transport_digest,
            "body_bytes": len(body), "transport_bytes": len(envelope)}
        assert db.execute("SELECT count(*) FROM intake_refusals").fetchone()[0] == 0
    assert gateway.path.stat().st_size < 512_000
    assert all(s not in gateway.path.read_bytes() for s in (b"PRIVATE-BODY", b"PRIVATE-ENVELOPE"))
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert reopened.ingest(req.binding, body=body, transport=envelope) == result
    assert len(reopened.validation_history(req.binding)) == 1
    assert reopened.revalidate(req.binding) == result
    history = reopened.validation_history(req.binding)
    assert len(history) == 2
    assert all(h["invocation"]["ipc_id"] is None and h["result_record_id"] == result.record_id for h in history)
    assert reopened.build_ledger([req.lineage_id]) == ledger
    assert sent == received == []
    for candidate, env in ((raw(payload(req)), envelope), (body + b"x", envelope), (body, b"repaired")):
        assert_refused("delivery_conflict", lambda: reopened.ingest(req.binding, body=candidate, transport=env))
    if correction:
        assert reopened.correction_request(original.binding) == req
        for binding in (original.binding, req.binding):
            assert_refused("result_unavailable", lambda: reopened.reserve_correction(binding))
    else:
        corrected = reopened.reserve_correction(req.binding)
        context = reopened.correction_context(corrected.binding)
        assert context["original_body"] is None
        assert context["original_body_retained"] is False
        assert context["original_body_absence_reason"] == "limit_exceeded"
        assert context["original_body_digest"] == result.body_digest
        assert context["original_body_bytes"] == len(body)
        assert context["original_brief"] == b"Inspect the frozen contract"
        assert context["failure"] == asdict(result)
        prompt = reopened.build_request(corrected.binding).prompt
        for text in ('"original_body_base64":null', '"original_body_retained":false',
                     '"original_body_bytes":4097', result.body_digest, "limit_exceeded", "Inspect the frozen contract",
                     "substantive_replacement", "over-limit original bytes were not retained"):
            assert text in prompt
        assert "PRIVATE-BODY" not in prompt
        accepted = ingest(reopened, corrected)
        assert accepted.usable_vote and accepted.replaces_record_id == result.record_id
        assert reopened.revalidate(req.binding) == result
        assert reopened.build_ledger([req.lineage_id])["records"] == [accepted.record_id]


@pytest.mark.parametrize("governed_provenance", [(), ("HOST_ATTESTED",), ("TRANSPORT_CAPTURED",)])
def test_governed_provenance_requires_explicit_class_admission(tmp_path, source, governed_provenance):
    policy = TestPolicy(governed=True)
    policy.authorize = lambda _: c.Admission(eligibility="GOVERNED",
        permitted_provenance=("HOST_ATTESTED", "TRANSPORT_CAPTURED"), governed_provenance=governed_provenance)
    gateway = c.ReviewCoordinator(tmp_path / "private", policy=policy)
    for provenance in ("HOST_ATTESTED", "TRANSPORT_CAPTURED"):
        req = request(gateway, source)
        assert req.value["admission"]["governed_provenance"] == list(governed_provenance)
        register(gateway, req, provenance)
        body = raw(payload(req))
        result = gateway.ingest(req.binding, body=body, transport=body, captured_body=body)
        assert result.usable and result.governed_eligible == (provenance in governed_provenance)


@pytest.mark.parametrize("field,value", [("permitted_provenance", "HOST_ATTESTED"),
    ("permitted_provenance", ()), ("permitted_provenance", ([],)),
    ("permitted_provenance", ("HOST_ATTESTED", "HOST_ATTESTED")),
    ("governed_provenance", "HOST_ATTESTED"), ("governed_provenance", ([],)),
    ("governed_provenance", ("SELF_ATTESTED",)), ("governed_provenance", ("TRANSPORT_CAPTURED",)),
    ("governed_provenance", ("HOST_ATTESTED", "HOST_ATTESTED"))])
def test_malformed_provenance_policy_is_closed_refusal(gateway, source, field, value):
    gateway.policy.authorize = lambda _: replace(c.Admission("GOVERNED"), **{field: value})
    assert_refused("binding_mismatch", lambda: request(gateway, source))


def test_transport_neutral_lineage_fixture_is_executed(tmp_path, source):
    fixture = json.loads((Path(__file__).parent / "data" / "typed_review_contract_vectors.json").read_text())["lineage"]
    for scenario in fixture["scenarios"]:
        directory = tmp_path / scenario["name"]
        policy = TestPolicy()
        admission = fixture["environment"]["policy"]
        policy.authorize = lambda _: c.Admission(**{**admission,
            "permitted_provenance": tuple(admission["permitted_provenance"]),
            "governed_provenance": tuple(admission["governed_provenance"])})
        gateway = c.ReviewCoordinator(directory, policy=policy)
        saved = {}

        def resolve(value):
            if isinstance(value, str) and value.startswith("$"):
                name, key = value[1:].split(".")
                return saved[name][key]
            if isinstance(value, dict):
                return {k: resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            return value

        for step in scenario["steps"]:
            inputs, expected = resolve(step["inputs"]), resolve(step["expect"])
            result = None
            try:
                op = step["op"]
                if op == "create":
                    brief = inputs.pop("brief_utf8").encode("utf-8")
                    result = gateway.create_request(**inputs, brief=brief, source_snapshot=source)
                elif op == "ingest":
                    req = gateway.load_request(inputs["binding"])
                    gateway.register_transport(req.binding, host_identity=fixture["environment"]["host_identity"],
                        provenance=fixture["environment"]["provenance"], identity={"operationId": req.attempt_id})
                    result = gateway.ingest(req.binding, body=c.canonical_json(inputs["body_json"]) + b" " * inputs.get("body_suffix_spaces", 0),
                        transport=inputs["envelope_utf8"].encode("utf-8"), evidence_digests=inputs["evidence_digests"])
                elif op == "reserve":
                    result = gateway.reserve_correction(inputs["binding"])
                elif op == "recover":
                    result = gateway.correction_request(inputs["binding"])
                elif op == "restart":
                    gateway = c.ReviewCoordinator(directory, policy=policy)
                elif op == "revalidate":
                    result = gateway.revalidate(inputs["binding"])
                else:
                    pytest.fail(f"unimplemented fixture operation {op}")
                assert "refused" not in expected, (scenario["name"], step)
            except c.ReviewRefused as exc:
                assert expected == {"refused": exc.code}, (scenario["name"], step)
            if result is not None:
                fields = ({**result.value, "binding": result.binding} if isinstance(result, c.FrozenRequest)
                          else {**asdict(result), "usable_vote": result.usable_vote})
                for key, value in expected.items():
                    if key.endswith("_not"):
                        assert fields[key[:-4]] != value
                    else:
                        assert fields[key] == value
                if "save" in step:
                    saved[step["save"]] = fields
            standing = resolve(step["standing"])
            lineage_id = saved["original"]["lineage_id"]
            with sqlite3.connect(gateway.path) as db:
                assert db.execute("SELECT standing FROM lineages WHERE id=?", (lineage_id,)).fetchone()[0] == standing
            if standing is None:
                assert_refused("result_unavailable", lambda: gateway.build_ledger([lineage_id]))
            else:
                assert gateway.build_ledger([lineage_id])["records"] == [standing]


def test_default_governed_admission_keeps_host_attested_non_gating(gateway, source):
    gateway.policy.authorize = lambda _: c.Admission("GOVERNED")
    req = request(gateway, source)
    assert req.value["admission"]["governed_provenance"] == []
    assert not ingest(gateway, req).governed_eligible
    changed = req.value
    changed["admission"]["governed_provenance"] = ["HOST_ATTESTED"]
    assert c.canonical_digest("request", changed) != req.binding


@pytest.mark.parametrize("field", ["raw", "transport", "evidence"])
def test_revalidation_delivery_identity_tampering_preserves_history(gateway, source, field):
    req = request(gateway, source)
    first = ingest(gateway, req)
    with sqlite3.connect(gateway.path) as db:
        old = db.execute(f"SELECT {field} FROM deliveries WHERE binding=?", (req.binding,)).fetchone()[0]
        changed = {"raw": raw(payload(req, summary="Changed body")), "transport": b"Changed envelope", "evidence": '{"E1":"changed"}'}[field]
        db.execute(f"UPDATE deliveries SET {field}=? WHERE binding=?", (changed, req.binding))
    result = gateway.revalidate(req.binding)
    assert result.rejection_code == "result_unavailable" and not result.usable
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))
    assert_refused("result_unavailable", lambda: gateway.build_ledger([req.lineage_id]))
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT standing FROM lineages WHERE id=?", (req.lineage_id,)).fetchone()[0] == first.record_id
        db.execute(f"UPDATE deliveries SET {field}=? WHERE binding=?", (old, req.binding))
    assert gateway.revalidate(req.binding) == first


def test_prefreeze_request_cannot_infer_governed_provenance(gateway, source):
    req = request(gateway, source)
    old = req.value
    old["admission"].pop("governed_provenance")
    old = c.FrozenRequest(c.canonical_json(old).decode())
    with sqlite3.connect(gateway.path) as db:
        db.execute("UPDATE requests SET binding=?, body=? WHERE binding=?", (old.binding, old._json, req.binding))
    assert_refused("result_unavailable", lambda: gateway.load_request(old.binding))
    assert_refused("result_unavailable", lambda: gateway.revalidate(old.binding))
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(old.binding))


def test_changed_worker_value_keeps_invalid_identity_and_actual_history(gateway, source, monkeypatch):
    req = request(gateway, source)
    sent, received = observe_worker(monkeypatch)
    parse = b.parse_review_response

    def mutate(*args, **kw):
        reply = parse(*args, **kw)
        return replace(reply, value={**reply.value, "summary": "negative mutation"})

    with monkeypatch.context() as patch:
        patch.setattr(b, "parse_review_response", mutate)
        first = ingest(gateway, req)
        assert first.rejection_code == "baml_changed_value"
        reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
        assert reopened.revalidate(req.binding) == first
    history = reopened.validation_history(req.binding)
    assert len(sent) == len(received) == len(history) == 2
    assert history[0]["invocation"]["ipc_id"] != history[1]["invocation"]["ipc_id"]
    assert [h["invocation"]["ipc_id"] for h in history] == [f["id"] for f in received]
    recovered = reopened.revalidate(req.binding)
    assert recovered.usable_vote and recovered.record_id != first.record_id


@pytest.mark.parametrize("mutation", ["body", "both", "evidence", "capture", "admission"])
def test_oversize_does_not_skip_host_checks(gateway, source, mutation):
    req = request(gateway, source, byte_limit=1024, evidence=[{"handle": "E1", "sha256": "c" * 64}])
    register(gateway, req, "TRANSPORT_CAPTURED")
    body = b"x" * 1025
    env = b"e" * (c.MAX_TRANSPORT_BYTES + 1) if mutation == "both" else b"env"
    kw = {"captured_body": body, "evidence_digests": {"E1": "c" * 64}}
    if mutation in ("body", "both", "capture"):
        kw["captured_body"] = body[:-1]
    elif mutation == "evidence":
        kw["evidence_digests"] = {"E1": "d" * 64}
    else:
        gateway.policy.trust = False
    assert_refused("binding_mismatch", lambda: gateway.ingest(req.binding, body=body, transport=env, **kw))
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    gateway.policy.trust = True
    result = gateway.ingest(req.binding, body=body, transport=env, captured_body=body, evidence_digests={"E1": "c" * 64})
    assert result.rejection_code == "limit_exceeded"


def test_envelope_repair_binds_authentic_body_across_restart(gateway, source):
    req = request(gateway, source, byte_limit=4096)
    register(gateway, req)
    body = raw(payload(req))
    envelope = b"x" * (c.MAX_TRANSPORT_BYTES + 1)
    assert_refused("limit_exceeded", lambda: gateway.ingest(req.binding, body=body, transport=envelope))
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    for candidate in (raw(payload(req, summary="another reply")), b"x" * 4097):
        assert_refused("delivery_conflict", lambda: reopened.ingest(req.binding, body=candidate, transport=b"repaired"))
    assert_refused("result_unavailable", lambda: reopened.reserve_correction(req.binding))
    assert reopened.ingest(req.binding, body=body, transport=b"repaired").usable_vote
    assert_refused("delivery_conflict", lambda: reopened.ingest(req.binding, body=body, transport=envelope))


@pytest.mark.parametrize("when", ["before_validation", "after_validation"])
def test_oversize_claim_and_rejection_roll_back_together(gateway, source, monkeypatch, when):
    req = request(gateway, source, byte_limit=1024)
    register(gateway, req)
    body = b"x" * 1025
    validate = gateway._validate
    with monkeypatch.context() as patch:
        def crash(*args, **kw):
            if when == "after_validation":
                validate(*args, **kw)
            raise SystemExit(23)
        patch.setattr(gateway, "_validate", crash)
        with pytest.raises(SystemExit):
            gateway.ingest(req.binding, body=body, transport=body)
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM validations").fetchone()[0] == 0
        assert db.execute("SELECT standing FROM lineages").fetchone()[0] is None
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    result = reopened.ingest(req.binding, body=body, transport=body)
    assert result.rejection_code == "limit_exceeded"
    assert reopened.build_ledger([req.lineage_id])["records"] == [result.record_id]


def test_digest_only_missing_source_refuses_then_recovers(gateway, source, monkeypatch):
    req = request(gateway, source, byte_limit=1024)
    register(gateway, req)
    body = b"x" * 1025
    first = gateway.ingest(req.binding, body=body, transport=body)
    with sqlite3.connect(gateway.path) as db:
        saved = db.execute("SELECT fingerprint, files FROM sources").fetchone()
        db.execute("DELETE FROM sources")
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **kw: pytest.fail("digest-only parse"))
    assert_refused("baml_unavailable", lambda: gateway.ingest(req.binding, body=body, transport=body))
    assert gateway.revalidate(req.binding).rejection_code == "baml_unavailable"
    assert_refused("result_unavailable", lambda: gateway.reserve_correction(req.binding))
    with sqlite3.connect(gateway.path) as db:
        db.execute("INSERT INTO sources VALUES (?, ?)", saved)
    assert gateway.revalidate(req.binding) == first
    assert gateway.reserve_correction(req.binding).value["replaces_record_id"] == first.record_id


@pytest.mark.parametrize("change", ["raw", "omitted"])
def test_digest_only_cannot_accept_fabricated_retained_bytes(gateway, source, monkeypatch, change):
    req = request(gateway, source, byte_limit=1024)
    register(gateway, req)
    first = gateway.ingest(req.binding, body=b"x" * 1025, transport=b"env")
    correction = gateway.reserve_correction(req.binding)
    with sqlite3.connect(gateway.path) as db:
        if change == "raw":
            db.execute("UPDATE deliveries SET raw=?", (raw(payload(req)),))
        else:
            db.execute("UPDATE deliveries SET omitted=NULL, raw=?, transport=?", (raw(payload(req)), b"env"))
    monkeypatch.setattr(b, "parse_review_response", lambda *a, **kw: pytest.fail("fabricated bytes reached worker"))
    if change == "raw":
        assert_refused("result_unavailable", lambda: gateway.revalidate(req.binding))
    else:
        assert gateway.revalidate(req.binding).rejection_code == "result_unavailable"
    assert_refused("result_unavailable", lambda: gateway.correction_context(correction.binding))
    assert_refused("result_unavailable", lambda: gateway.build_request(correction.binding))
    assert_refused("binding_mismatch", lambda: gateway.private_body(first.record_id))


def test_prefreeze_delivery_migration_preserves_bytes_ids_and_history(gateway, source):
    req = request(gateway, source)
    first = ingest(gateway, req)
    before = gateway.validation_history(req.binding)
    with sqlite3.connect(gateway.path) as db:
        db.execute("ALTER TABLE deliveries RENAME TO new_deliveries")
        db.execute("""CREATE TABLE deliveries (binding TEXT PRIMARY KEY, identity TEXT NOT NULL,
            raw BLOB NOT NULL, transport BLOB NOT NULL, evidence TEXT NOT NULL, latest TEXT)""")
        db.execute("INSERT INTO deliveries SELECT binding, identity, raw, transport, evidence, latest FROM new_deliveries")
        db.execute("DROP TABLE new_deliveries")
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    assert ingest(reopened, req) == first
    assert reopened.validation_history(req.binding) == before
    assert reopened.revalidate(req.binding) == first
    with sqlite3.connect(reopened.path) as db:
        assert db.execute("SELECT raw, transport, omitted FROM deliveries").fetchone() == (raw(payload(req)), raw(payload(req)), None)


@pytest.mark.parametrize("candidates", [(0, 0, 1), (0, 0, 2)])
def test_digest_only_process_conflict_is_atomic(gateway, source, candidates):
    req = request(gateway, source, byte_limit=1024)
    register(gateway, req)
    script = """
import json, sys
from pathlib import Path
from test_review_contract import TestPolicy, payload, raw
from phase_loop_runtime.review_contract import ReviewCoordinator, ReviewRefused
g = ReviewCoordinator(Path(sys.argv[1]), policy=TestPolicy())
req = g.load_request(sys.argv[2])
n = int(sys.argv[3])
body = raw(payload(req)) if n == 2 else bytes([120+n]) * 1025
try:
    rec = g.ingest(req.binding, body=body, transport=b'env')
    print(json.dumps({'id':rec.record_id, 'code':rec.rejection_code, 'body':rec.body_digest}))
except ReviewRefused as e:
    print(json.dumps({'refused':e.code}))
"""
    procs = [subprocess.Popen([sys.executable, "-c", script, str(gateway.directory), req.binding, str(n)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[2]) for n in candidates]
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=45)
        assert proc.returncode == 0, err
        outputs.append(json.loads(out))
    successful = [o for o in outputs if "id" in o]
    assert len({o["id"] for o in successful}) == 1
    assert sum(o == {"refused": "delivery_conflict"} for o in outputs) in (1, 2)
    with sqlite3.connect(gateway.path) as db:
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM validations").fetchone()[0] == 1
        assert db.execute("SELECT standing FROM lineages").fetchone()[0] == successful[0]["id"]


@pytest.mark.parametrize("body", [b"", b"\xff", b"{}"])
def test_retained_invalid_correction_context_is_lossless(gateway, source, body):
    import base64
    req = request(gateway, source)
    register(gateway, req)
    failed = gateway.ingest(req.binding, body=body, transport=b"env")
    correction = gateway.reserve_correction(req.binding)
    context = gateway.correction_context(correction.binding)
    assert context["original_body"] == body and context["original_body_retained"] is True
    assert context["original_body_absence_reason"] is None
    assert context["original_body_bytes"] == len(body)
    assert context["original_body_digest"] == failed.body_digest == hashlib.sha256(body).hexdigest()
    prompt = gateway.build_request(correction.binding).prompt
    assert '"original_body_base64":' + json.dumps(base64.b64encode(body).decode()) in prompt
    assert "over-limit original bytes were not retained" not in prompt


def test_digest_only_seat_president_resume_keeps_usable_ruling(gateway, source, monkeypatch):
    seat = request(gateway, source, byte_limit=1024)
    register(gateway, seat)
    invalid = gateway.ingest(seat.binding, body=b"x" * 1025, transport=b"env")
    ledger = gateway.build_ledger([seat.lineage_id])
    president = request(gateway, source, function="EmitReviewDecision", ledger=ledger)
    ruling = ingest(gateway, president)
    assert ruling.usable_ruling
    reopened = c.ReviewCoordinator(gateway.directory, policy=TestPolicy())
    sent, received = observe_worker(monkeypatch)
    assert reopened.revalidate(seat.binding) == invalid
    assert sent == received == []
    assert reopened.build_ledger([seat.lineage_id]) == ledger
    assert reopened.revalidate(president.binding) == ruling
    assert len(sent) == len(received) == 1
    assert reopened.validation_history(president.binding)[-1]["invocation"]["ipc_id"] == received[0]["id"] != ruling.ipc_id
