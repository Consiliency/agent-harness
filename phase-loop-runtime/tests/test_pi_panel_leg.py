"""PI seat leg (plans/phase-plan-v1-seats-PI.md, lane SL-1).

SL-1.0: the frozen fixtures under tests/data/seats_pi and the reference checks for their formats
(contract plans/artifacts/seats-pi-route-contract-v3.md §7). The checks below are the format
reference that SL-1.1 and SL-1.2 implement in the adapter. They are not the adapter.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from phase_loop_runtime.panel_invoker import terminal_verdict

DATA = Path(__file__).parent / "data" / "seats_pi"
UNLISTED = {"manifest.json", "README.md"}
PROVENANCE = {"recorded", "stub_witness", "derived", "synthetic"}
EVENT_TYPES = {
    "session", "agent_start", "turn_start", "turn_end", "message_start", "message_update", "message_end",
    "tool_execution_start", "tool_execution_update", "tool_execution_end", "agent_end",
    "agent_before_settle", "agent_settled",
}
LISTED_TOOLS = {"read", "grep", "find", "ls", "bash"}
WITNESS_FIELDS = {"schema", "ordinal", "status", "completed", "response_id", "upstream_model", "output_sha256"}
REQUESTED_MODEL = "gpt-6.1-sol"
SUCCESS = ("tooled-success", "tooled-probe-differing-model")
ERRORS = ("http-401", "http-403", "http-429", "http-500", "transport-reset", "stream-failed-2xx")


def manifest():
    return json.loads((DATA / "manifest.json").read_text())


def manifest_mismatches(root):
    doc = json.loads((root / "manifest.json").read_text())
    listed = {e["path"]: e["sha256"] for e in doc["files"]}
    problems = []
    for rel, digest in sorted(listed.items()):
        path = root / rel
        if not path.is_file():
            problems.append(("missing", rel))
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(("digest", rel))
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel not in listed and rel not in UNLISTED:
            problems.append(("unlisted", rel))
    return problems


def _is_hex64(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def witness_record_ok(rec):
    if not isinstance(rec, dict) or set(rec) != WITNESS_FIELDS or rec["schema"] != "pi_seat_witness.v1":
        return False
    if type(rec["ordinal"]) is not int or type(rec["status"]) is not int or type(rec["completed"]) is not bool:
        return False
    if not 100 <= rec["status"] <= 599:
        return False
    for key in ("response_id", "upstream_model"):
        if rec[key] is not None and not isinstance(rec[key], str):
            return False
    if rec["output_sha256"] is not None and not _is_hex64(rec["output_sha256"]):
        return False
    if rec["completed"]:
        return 200 <= rec["status"] < 300 and None not in (rec["response_id"], rec["upstream_model"],
                                                           rec["output_sha256"])
    return True


def witness_refusal(text, settled_after_ordinal=None):
    """None for an acceptable witness sequence, else the C1 refusal reason."""
    records = []
    for line in text.splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            return "unparseable"
    seen_ids = set()
    for index, rec in enumerate(records, start=1):
        if not witness_record_ok(rec):
            return "schema"
        if rec["ordinal"] < index:
            return "duplicate_ordinal"
        if rec["ordinal"] > index:
            return "ordinal_gap"
        if rec["response_id"] is not None:
            if rec["response_id"] in seen_ids:
                return "duplicate_response_id"
            seen_ids.add(rec["response_id"])
        if settled_after_ordinal is not None and rec["ordinal"] > settled_after_ordinal:
            return "record_after_settled"
    return None


def grammar_problem(text):
    """None when a stream satisfies the contract §7 terminal grammar, else the first problem."""
    events = []
    for line in text.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            return "unparseable"
    if not events or events[0].get("type") != "session":
        return "no_session_header"
    for ev in events:
        if ev.get("type") not in EVENT_TYPES:
            return "unknown_event_type"
        if ev["type"].startswith("tool_execution_") and ev.get("toolName") not in LISTED_TOOLS:
            return "unknown_tool"
    if sum(ev["type"] == "session" for ev in events) != 1:
        return "duplicate_session"
    settled = [i for i, ev in enumerate(events) if ev["type"] == "agent_settled"]
    if not settled:
        return "missing_settled"
    if len(settled) > 1 or settled[0] != len(events) - 1:
        return "post_terminal"
    if events[-1].get("aborted") is not False:
        return "aborted"
    if events[-2]["type"] != "agent_end":
        return "no_agent_end"
    final = final_assistant(events)
    if final is None or final.get("stopReason") != "stop" or final.get("errorMessage"):
        return "final_not_clean"
    return None


def final_assistant(events):
    ends = [ev["message"] for ev in events if ev["type"] == "message_end" and ev["message"].get("role") == "assistant"]
    return ends[-1] if ends else None


def final_text(message):
    return "".join(block["text"] for block in message["content"] if block["type"] == "text")


def verdict_ineligibility(stream_text, witness_records, proxy_summary, admitted_models):
    """None when a run's verdict may count (contract §11), else the first failing input."""
    if grammar_problem(stream_text) is not None:
        return "grammar"
    if proxy_summary["allowed_inference_count"] != len(witness_records):
        return "count_mismatch"
    final = final_assistant([json.loads(line) for line in stream_text.splitlines()])
    rec = next((r for r in witness_records if r["response_id"] == final.get("responseId")), None)
    if rec is None:
        return "no_witness_for_final"
    if rec is not witness_records[-1]:
        return "not_final_response"
    if not (rec["completed"] and 200 <= rec["status"] < 300):
        return "not_completed"
    text = final_text(final)
    if rec["output_sha256"] != hashlib.sha256(text.encode()).hexdigest():
        return "digest_mismatch"
    if rec["upstream_model"] not in admitted_models.get(final.get("model"), ()):
        return "model_not_admitted"
    if terminal_verdict(text) is None:
        return "no_verdict"
    return None


def events(name):
    return [json.loads(line) for line in (DATA / "events" / f"{name}.jsonl").read_text().splitlines()]


def witness(name):
    return [json.loads(line) for line in (DATA / "witness" / f"{name}.jsonl").read_text().splitlines()]


def proxy(name):
    return json.loads((DATA / "proxy" / f"{name}.json").read_text())


def entry(rel):
    return next(e for e in manifest()["files"] if e["path"] == rel)


def test_manifest_lists_every_fixture_with_its_digest():
    assert manifest_mismatches(DATA) == []


def test_manifest_check_detects_a_changed_byte_and_an_unlisted_file(tmp_path):
    root = tmp_path / "seats_pi"
    shutil.copytree(DATA, root)
    target = root / "witness" / "tooled-success.jsonl"
    target.write_bytes(target.read_bytes().replace(b'"ordinal":2', b'"ordinal":3'))
    (root / "events" / "planted.jsonl").write_text("{}\n")
    assert manifest_mismatches(root) == [("digest", "witness/tooled-success.jsonl"),
                                         ("unlisted", "events/planted.jsonl")]


def test_manifest_pins_the_recording_inputs_and_lists_what_is_owed():
    doc = manifest()
    assert doc["schema"] == "pi_seat_fixtures.v1"
    assert doc["pi"]["version"] == "1.6.0" and _is_hex64(doc["pi"]["cli_bundle_sha256"])
    assert doc["node"]["version"] == "v24.22.3" and _is_hex64(doc["node"]["binary_sha256"])
    assert doc["command"][1] == "--offline" and "--api-key" not in doc["command"] and "--" not in doc["command"]
    assert doc["settings"] == {"transport": "sse", "cacheWarming": "off",
                               "retry": {"enabled": False, "maxRetries": 0, "provider": {"maxRetries": 0}}}
    assert doc["witness_channel"]["family"] == "AF_UNIX"
    assert {o["by"] for o in doc["owed"]} >= {"SL-1.2", "SL-3.6"}
    for e in doc["files"]:
        assert e["provenance"] in PROVENANCE, e["path"]
        if e["provenance"] == "derived" or e["path"].startswith("witness/synthetic/"):
            assert e["derived_from"] in {f["path"] for f in doc["files"]}, e["path"]
        if e["kind"] == "event_stream" and e["provenance"] == "recorded":
            assert e["launch"] and _is_hex64(e["raw_sha256"]), e["path"]


HOST_MARKERS = ("/home/", "/mnt/", "/Users/", "eyJ", "Bearer ", "sk-")


def host_marker_hits(root):
    hits = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        text = path.read_text()
        hits.extend((path.relative_to(root).as_posix(), m) for m in HOST_MARKERS if m in text)
    return hits


def test_fixtures_carry_no_host_paths_or_token_shapes():
    assert host_marker_hits(DATA) == []


def test_host_marker_scan_detects_a_planted_path(tmp_path):
    root = tmp_path / "seats_pi"
    shutil.copytree(DATA, root)
    (root / "events" / "planted.jsonl").write_text('{"cwd":"/home/someone/work"}\n')
    assert host_marker_hits(root) == [("events/planted.jsonl", "/home/")]


@pytest.mark.parametrize("name", SUCCESS)
def test_recorded_success_streams_satisfy_the_terminal_grammar(name):
    text = (DATA / "events" / f"{name}.jsonl").read_text()
    assert grammar_problem(text) is None
    evs = events(name)
    assistant_ends = [ev for ev in evs if ev["type"] == "message_end" and ev["message"].get("role") == "assistant"]
    assert [m["message"]["stopReason"] for m in assistant_ends] == ["toolUse", "stop"]
    assert [ev["toolName"] for ev in evs if ev["type"] == "tool_execution_start"] == ["bash"]


@pytest.mark.parametrize("name", ERRORS)
def test_recorded_error_streams_end_in_an_assistant_error_with_aborted_false(name):
    evs = events(name)
    assert grammar_problem((DATA / "events" / f"{name}.jsonl").read_text()) == "final_not_clean"
    assert evs[-1] == {"type": "agent_settled", "aborted": False}
    final = final_assistant(evs)
    assert final["stopReason"] == "error" and final["errorMessage"]
    assert entry(f"events/{name}.jsonl")["pi_exit_code"] == 0


@pytest.mark.parametrize(("name", "reason"), [
    ("malformed-line", "unparseable"),
    ("duplicate-session", "duplicate_session"),
    ("duplicate-settled", "post_terminal"),
    ("post-terminal", "post_terminal"),
    ("missing-settled", "missing_settled"),
    ("settled-aborted", "aborted"),
    ("unknown-tool", "unknown_tool"),
    ("no-session-header", "no_session_header"),
    ("missing-agent-end", "no_agent_end"),
    ("misplaced-agent-end", "no_agent_end"),
    ("tooled-verdict-eligible", None),
])
def test_derived_streams_give_their_stated_grammar_result(name, reason):
    assert grammar_problem((DATA / "events" / "derived" / f"{name}.jsonl").read_text()) == reason


@pytest.mark.parametrize("name", SUCCESS + ERRORS)
def test_stub_witness_records_follow_the_frozen_schema(name):
    assert witness_refusal((DATA / "witness" / f"{name}.jsonl").read_text()) is None


@pytest.mark.parametrize("path", sorted((DATA / "witness" / "synthetic").glob("*.jsonl")), ids=lambda p: p.stem)
def test_synthetic_witness_sequences_are_refused_for_their_stated_reason(path):
    meta = entry(path.relative_to(DATA).as_posix())
    assert meta["validity"] == "invalid"
    assert witness_refusal(path.read_text(), meta.get("settled_after_ordinal")) == meta["expected_refusal"]


@pytest.mark.parametrize("name", SUCCESS)
def test_witness_digest_and_response_id_bind_the_final_assistant_text(name):
    final = final_assistant(events(name))
    text = "".join(block["text"] for block in final["content"] if block["type"] == "text")
    rec = next(r for r in witness(name) if r["response_id"] == final["responseId"])
    assert rec["completed"] and rec["status"] == 200
    assert rec["output_sha256"] == hashlib.sha256(text.encode()).hexdigest()


def test_identical_error_bodies_on_the_wire_are_told_apart_only_by_the_witness_status():
    names = ("http-401", "http-403", "http-429", "http-500")
    digests = {proxy(n)["requests"][0]["response_body_sha256"] for n in names}
    assert len(digests) == 1 and _is_hex64(digests.pop())
    assert [proxy(n)["requests"][0]["status_sent"] for n in names] == [401, 403, 429, 500]
    assert [witness(n)[0]["status"] for n in names] == [401, 403, 429, 500]
    # Pi's own text cannot carry the distinction: 401, 403 and 500 read the same, and 429 is rewritten.
    assert len({final_assistant(events(n))["errorMessage"] for n in ("http-401", "http-403", "http-500")}) == 1


@pytest.mark.parametrize("name", ERRORS)
def test_admitted_inference_posts_are_counted_whatever_the_response_status(name):
    p = proxy(name)
    assert p["pi_inference_count"] == 1 and p["allowed_inference_count"] == 1
    [rec] = witness(name)
    assert rec["status"] == p["requests"][0]["status_sent"]


def test_tool_originated_post_leaves_witness_and_proxy_counts_unequal():
    p = proxy("tooled-success")
    assert [r["origin"] for r in p["requests"]] == ["pi", "tool_descendant", "pi"]
    assert p["allowed_inference_count"] == 3
    assert len(witness("tooled-success")) == 2


def test_differing_upstream_model_shows_only_in_the_witness():
    final = final_assistant(events("tooled-probe-differing-model"))
    assert final["model"] == REQUESTED_MODEL
    rec = next(r for r in witness("tooled-probe-differing-model") if r["response_id"] == final["responseId"])
    assert rec["upstream_model"] not in (None, REQUESTED_MODEL)


def test_incomplete_responses_are_witnessed_as_not_completed():
    for name in ("transport-reset", "stream-failed-2xx"):
        [rec] = witness(name)
        assert rec["status"] == 200 and rec["completed"] is False and rec["output_sha256"] is None


def test_trust_preconditions_were_measured_and_held():
    doc = json.loads((DATA / "measurements" / "trust-preconditions.json").read_text())
    assert doc["yama_ptrace_scope"] >= 1
    assert doc["tool_path"] == ["pi", "bash", "python3"] and doc["tool_cap_eff"] == "0000000000000000"
    assert doc["channel"] == {"family": "AF_UNIX", "type": "SOCK_STREAM", "named": False}
    pre = doc["preconditions"]
    assert pre["no_inheritance"] == {"tool_holds_witness": False, "intermediate_shell_holds_witness": False}
    assert pre["no_reopen"] == {"proc_fd_reopen_wronly": "ENXIO", "pidfd_getfd": "EPERM"}
    assert pre["no_ancestor_write"] == {"ptrace_attach": "EPERM", "ptrace_seize": "EPERM",
                                        "proc_mem_rdwr": "EACCES", "process_vm_readv": "EPERM"}
    assert doc["positive_control_own_child"] == {"PTRACE_SEIZE_child": "OK", "pidfd_getfd_child": "OK",
                                                 "proc_mem_rdwr_child": "OK", "reopen_socket_child": "ENXIO"}
    assert doc["forged_witness_records"] == 0


def _store(name):
    return json.loads((DATA / "stores" / f"{name}.json").read_text())


def test_valid_store_keeps_only_the_listed_fields_and_an_empty_refresh():
    doc = _store("valid")
    assert list(doc) == ["openai-codex"]
    e = doc["openai-codex"]
    assert set(e) == {"type", "access", "refresh", "expires"} and e["refresh"] == "" and e["type"] == "oauth"
    claims = e["access"]["$fixture_jwt"]["claims"]
    assert e["expires"] == claims["exp"] * 1000
    assert claims["iat"] * 1000 <= manifest()["fixture_now_ms"] < claims["exp"] * 1000


def test_every_invalid_store_states_its_refusal_and_the_duplicate_key_is_real():
    for e in manifest()["files"]:
        if e["kind"] == "store":
            assert (e["validity"] == "valid") == (e["expected_refusal"] is None), e["path"]
    pairs = []
    json.loads((DATA / "stores" / "duplicate-key.json").read_text(), object_pairs_hook=lambda kv: pairs.append(kv) or dict(kv))
    assert [k for k, _ in pairs[-1]] == ["openai-codex", "openai-codex"]


ELIGIBLE = "tooled-verdict-eligible"


def _route_admitted():
    return json.loads((DATA / "routes" / "route-record.synthetic.json").read_text())["admitted_models"]


def _eligible_inputs():
    text = (DATA / "events" / "derived" / f"{ELIGIBLE}.jsonl").read_text()
    wit = [json.loads(line) for line in (DATA / "witness" / "derived" / f"{ELIGIBLE}.jsonl").read_text().splitlines()]
    prox = json.loads((DATA / "proxy" / "derived" / f"{ELIGIBLE}.json").read_text())
    return text, wit, prox


def test_derived_eligible_tooled_verdict_satisfies_every_eligibility_input():
    text, wit, prox = _eligible_inputs()
    final = final_assistant([json.loads(line) for line in text.splitlines()])
    assert prox["allowed_inference_count"] == len(wit) == 2
    assert [r["origin"] for r in prox["requests"]] == ["pi", "pi"]
    assert wit[-1]["response_id"] == final["responseId"] and wit[-1]["completed"] and wit[-1]["status"] == 200
    assert wit[-1]["output_sha256"] == hashlib.sha256(final_text(final).encode()).hexdigest()
    assert wit[-1]["upstream_model"] in _route_admitted()[final["model"]]
    assert terminal_verdict(final_text(final)) == "AGREE"
    assert witness_refusal((DATA / "witness" / "derived" / f"{ELIGIBLE}.jsonl").read_text()) is None
    assert verdict_ineligibility(text, wit, prox, _route_admitted()) is None
    meta = entry(f"events/derived/{ELIGIBLE}.jsonl")
    assert meta["provenance"] == "derived" and len(meta["transformations"]) == 3


@pytest.mark.parametrize(("name", "reason"), [
    ("tooled-success", "count_mismatch"),
    ("tooled-probe-differing-model", "count_mismatch"),
])
def test_recorded_tooled_runs_with_a_tool_originated_post_are_ineligible(name, reason):
    text = (DATA / "events" / f"{name}.jsonl").read_text()
    assert verdict_ineligibility(text, witness(name), proxy(name), _route_admitted()) == reason


def _final_message(evs):
    return next(ev["message"] for ev in reversed(evs)
                if ev["type"] == "message_end" and ev["message"].get("role") == "assistant")


def _set_final_text(evs, new):
    for block in _final_message(evs)["content"]:
        if block["type"] == "text":
            block["text"] = new


def _mutate(kind):
    text, wit, prox = _eligible_inputs()
    evs = [json.loads(line) for line in text.splitlines()]
    if kind == "tool_post":
        prox["allowed_inference_count"] += 1
    elif kind == "changed_verdict":
        _set_final_text(evs, final_text(_final_message(evs)).replace("AGREE", "DISAGREE"))
    elif kind == "unknown_response_id":
        wit[-1]["response_id"] = "resp_other"
    elif kind == "replayed_earlier_response":
        _final_message(evs)["responseId"] = wit[0]["response_id"]
    elif kind == "not_completed":
        wit[-1]["completed"] = False
    elif kind == "upstream_model":
        wit[-1]["upstream_model"] = "gpt-fixture-other-upstream"
    elif kind == "no_verdict":
        _set_final_text(evs, "No findings (offline fixture).")
        wit[-1]["output_sha256"] = hashlib.sha256(b"No findings (offline fixture).").hexdigest()
    text = "".join(json.dumps(ev) + "\n" for ev in evs)
    return text, wit, prox


@pytest.mark.parametrize(("kind", "reason"), [
    ("tool_post", "count_mismatch"),
    ("changed_verdict", "digest_mismatch"),
    ("unknown_response_id", "no_witness_for_final"),
    ("replayed_earlier_response", "not_final_response"),
    ("not_completed", "not_completed"),
    ("upstream_model", "model_not_admitted"),
    ("no_verdict", "no_verdict"),
])
def test_one_change_to_the_eligible_case_makes_it_ineligible(kind, reason):
    assert verdict_ineligibility(*_mutate(kind), _route_admitted()) == reason


def test_a_stream_failing_the_grammar_is_ineligible_even_with_matching_witness_and_counts():
    _, wit, prox = _eligible_inputs()
    text = (DATA / "events" / "derived" / "missing-agent-end.jsonl").read_text()
    assert verdict_ineligibility(text, wit, prox, _route_admitted()) == "grammar"
