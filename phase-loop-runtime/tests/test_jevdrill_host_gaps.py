"""JEVHOST host gaps, adapter half (GAPS §3.1, §3.2, §3.4, §3.5 row 5b, §3.6-§3.8, item-3 hook).

Every test is synthetic: a fake or unspawnable CLI, no provider, model or live JEV call.
Tests that need an adapter interface absent from the base fail at an explicit availability
assertion naming it, so the base outcome is recorded separately from semantic failures.
"""

import json
import sqlite3
import subprocess
import sys
import threading
import time
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from phase_loop_runtime import jevdrill_adapter
from phase_loop_runtime.host_integration import DEACTIVATION_REASONS, disconnect_advice
from phase_loop_runtime.jevdrill_adapter import JevDrillTransport, JevDrillUnavailable
from phase_loop_runtime.launcher import LaunchResult
from jevdrill_fixture_values import load_rows
from test_jevdrill_adapter import FIXTURES, adapter_fixture, fixture


def require(owner, *names):
    missing = [name for name in names if not hasattr(owner, name)]
    assert not missing, "adapter interface is unavailable: missing " + ", ".join(missing)
    return [getattr(owner, name) for name in names]


def spec_for(prepared, **overrides):
    selection = prepared["model_selection"]
    values = dict(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model=selection.model,
                  effective_effort=selection.effort, claude_route=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def result_for(**fields):
    return LaunchResult(command=["synthetic"], **{"returncode": 0, **fields})


def drain(adapter):
    while adapter.flush() != "empty":
        pass


def delivered(calls, run_id=None):
    reports = [value["event"] for command, value in calls if command == "report"]
    if run_id is not None:
        reports = [event for event in reports if event["execution_run_id"] == run_id]
    return sorted(reports, key=lambda event: event["source_sequence"])


def queued_event_types(adapter):
    with sqlite3.connect(adapter.queue.path) as db:
        rows = [json.loads(row[0])["event"] for row in db.execute("SELECT payload FROM reports")]
    return [event["payload"].get("event_type") for event in sorted(rows, key=lambda e: e["source_sequence"])]


class MonotonicClock:
    """A controlled stand-in for the adapter module's ``time``."""

    def __init__(self, seconds=1000.0):
        self.ns = int(seconds * 1_000_000_000)

    def monotonic_ns(self):
        return self.ns

    def monotonic(self):
        return self.ns / 1_000_000_000

    def advance_ms(self, ms):
        self.ns += ms * 1_000_000

    sleep = staticmethod(time.sleep)


def routed_fixture(tmp_path, monkeypatch=None, *, max_attempts=2, **options):
    """``adapter_fixture`` whose CLI answers each route for the routed task with a fresh decision."""
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path, **options)
    inputs["request"]["hard_constraints"]["max_attempts"] = max_attempts
    decisions = []

    def call(command, payload, **_kwargs):
        calls.append((command, deepcopy(payload)))
        if command == "notices":
            return {"schema_version": "1", "notices": []}
        if command == "report":
            return {"status": "accepted", "event_id": payload["event"]["event_id"], "durable": True}
        request = payload["request"]
        value = deepcopy(decision)
        value["details"].update(task_id=request["task_id"], request_id=request["envelope"]["request_id"],
                                routing_decision_id=str(uuid4()))
        decisions.append(value["details"]["routing_decision_id"])
        return value

    adapter.transport.call = call
    tasks = {}

    def task(name):
        if name not in tasks:
            value = deepcopy(inputs)
            value["request"]["task_id"] = str(uuid4())
            value["request"]["envelope"]["request_id"] = str(uuid4())
            tasks[name] = value
        return tasks[name]

    current = ["a"]
    adapter.inputs_for = lambda _context: deepcopy(task(current[0]))
    clock = None
    if monkeypatch is not None:
        clock = MonotonicClock()
        monkeypatch.setattr(jevdrill_adapter, "time", clock)
    return SimpleNamespace(adapter=adapter, inputs=inputs, decision=decision, kwargs=kwargs, calls=calls,
                           notices=notices, decisions=decisions, task=task, current=current, clock=clock)


def route_payloads(calls):
    return [payload for command, payload in calls if command == "route"]


# --- Item 1 (GAPS §3.1) ---------------------------------------------------------------------


def test_acceptance_failure_builds_bounded_retry_context(tmp_path, monkeypatch):
    env = routed_fixture(tmp_path, monkeypatch, max_attempts=2)
    adapter = env.adapter
    record, = require(adapter, "record_acceptance_outcome")
    launched = []

    def run(name):
        env.current[0] = name
        prepared = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
        decision_id = env.decisions[-1]
        result = adapter.launch(lambda spec, **_k: launched.append(name) or result_for(), spec_for(prepared))
        return result.jevdrill_execution_run["execution_run_id"], decision_id

    run_a, decision_a = run("a")
    run_b, decision_b = run("b")
    record(run_a, passed=False, failure_class="infrastructure")
    record(run_a, passed=False, failure_class="quality")  # duplicate verdict: no-op
    record(run_b, passed=False, failure_class="quality")
    env.clock.advance_ms(1200)

    # Each task's retry names that task's own run and decision.
    env.current[0] = "a"
    prepared_a = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    context_a = route_payloads(env.calls)[-1]["request"]["retry_context"]
    assert context_a == {"failure_class": "infrastructure", "failure_summary": "host_acceptance_failed:infrastructure",
                         "prior_execution_run_id": run_a, "prior_routing_decision_id": decision_a,
                         "remaining_attempts": 1, "remaining_time_ms": 5000 - 1200, "remaining_spend": None}
    env.current[0] = "b"
    prepared_b = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    second_b = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    context_b = route_payloads(env.calls)[-1]["request"]["retry_context"]
    assert (context_b["prior_execution_run_id"], context_b["prior_routing_decision_id"]) == (run_b, decision_b)
    assert context_b["failure_class"] == "quality" and context_b["remaining_attempts"] == 1

    # Two prepared bindings compete for task b's final slot: exactly one launches.
    before = list(launched)
    adapter.launch(lambda spec, **_k: launched.append("b") or result_for(), spec_for(prepared_b))
    with pytest.raises(JevDrillUnavailable, match="Retry budget is exhausted"):
        adapter.launch(lambda spec, **_k: launched.append("b") or result_for(), spec_for(second_b))
    assert launched[len(before):] == ["b"]

    # After exhaustion there is no route and no CLI contact.
    result_a = adapter.launch(lambda spec, **_k: result_for(returncode=1), spec_for(prepared_a))
    record(result_a.jevdrill_execution_run["execution_run_id"], passed=False, failure_class="infrastructure")
    contacted = len(env.calls)
    env.current[0] = "a"
    with pytest.raises(JevDrillUnavailable, match="Retry budget is exhausted"):
        adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    assert len(env.calls) == contacted

    # A context-free route with no verdict and an expired budget makes no CLI contact.
    run("c")
    env.clock.advance_ms(5000)
    contacted = len(env.calls)
    env.current[0] = "c"
    with pytest.raises(JevDrillUnavailable, match="Retry budget is exhausted"):
        adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    assert len(env.calls) == contacted

    # A duplicate pass changes neither state nor notices.
    run_d, _ = run("d")
    record(run_d, passed=True, failure_class=None)
    state = (deepcopy(adapter._ledger), dict(adapter._run_index), list(env.notices))
    record(run_d, passed=True, failure_class=None)
    record(str(uuid4()), passed=False, failure_class="quality")  # unknown run: no-op
    assert (adapter._ledger, adapter._run_index, env.notices) == state
    env.current[0] = "d"
    adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    assert route_payloads(env.calls)[-1]["request"]["retry_context"] is None


def test_supplied_retry_context_cannot_widen_or_bypass(tmp_path, monkeypatch):
    env = routed_fixture(tmp_path, monkeypatch, max_attempts=3)
    adapter = env.adapter
    record, = require(adapter, "record_acceptance_outcome")
    prepared = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    decision_id = env.decisions[-1]
    result = adapter.launch(lambda spec, **_k: result_for(returncode=1), spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    record(run_id, passed=False, failure_class="infrastructure")
    env.clock.advance_ms(1000)
    honest = {"failure_class": "infrastructure", "failure_summary": "caller summary",
              "prior_execution_run_id": run_id, "prior_routing_decision_id": decision_id,
              "remaining_attempts": 2, "remaining_time_ms": 4000, "remaining_spend": None}
    variants = {
        "widened_attempts": {"remaining_attempts": 3},
        "widened_time": {"remaining_time_ms": 4001},
        "other_run": {"prior_execution_run_id": str(uuid4())},
        "other_decision": {"prior_routing_decision_id": str(uuid4())},
        "other_class": {"failure_class": "quality"},
    }
    base = env.task("a")
    for name, change in variants.items():
        base["request"]["retry_context"] = {**honest, **change}
        routes = len(route_payloads(env.calls))
        refused = None
        try:
            adapter.prepare(mode="main", dry_run=False, **env.kwargs)
        except JevDrillUnavailable as exc:
            refused = exc
        assert len(route_payloads(env.calls)) == routes, f"{name}: a supplied context reached route"
        assert refused is not None and "unverified" in str(refused), name

    # An honest, narrower context is accepted and replaced by the host's own.
    base["request"]["retry_context"] = {**honest, "remaining_attempts": 1, "remaining_time_ms": 10}
    adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    assert route_payloads(env.calls)[-1]["request"]["retry_context"] == {
        **honest, "failure_summary": "host_acceptance_failed:infrastructure"}

    # An exhausted budget refuses a supplied context with no route.
    env.clock.advance_ms(4000)
    base["request"]["retry_context"] = {**honest, "remaining_time_ms": 0}
    routes = len(route_payloads(env.calls))
    with pytest.raises(JevDrillUnavailable, match="exhausted"):
        adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    assert len(route_payloads(env.calls)) == routes


# Erratum 1 (plans/amendments/jevhost-JEVHOST-host-gaps-erratum-1.md): the frozen
# test_jevdrill_adapter.py keeps route reachable; the safety property moves to a later point.


def test_unrecorded_supplied_context_never_launches(tmp_path):
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    forged = fixture("RouteRequest")["retry_context"]
    forged["remaining_spend"] = None
    inputs["request"]["retry_context"] = forged
    launched, refused = [], None
    try:
        prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
        adapter.launch(lambda spec, **_k: launched.append(spec) or result_for(), spec_for(prepared))
    except JevDrillUnavailable as exc:
        refused = exc
    assert launched == [], "a supplied retry context with no host record reached the executor"
    assert refused is not None and "no host retry record" in str(refused)
    assert not adapter._pending


def test_unjudged_attempt_is_refused_at_launch_admission(tmp_path):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)  # max_attempts=1
    first = adapter.prepare(mode="main", dry_run=False, **kwargs)
    adapter.launch(lambda spec, **_k: result_for(), spec_for(first))
    again = adapter.prepare(mode="main", dry_run=False, **kwargs)  # route may occur
    launched, refused = [], None
    try:
        adapter.launch(lambda spec, **_k: launched.append(spec) or result_for(), spec_for(again))
    except JevDrillUnavailable as exc:
        refused = exc
    assert launched == [], "a second launch spent an exhausted attempt budget"
    assert refused is not None and "Retry budget is exhausted" in str(refused)


# --- Item 2 (GAPS §3.2) ---------------------------------------------------------------------


def with_guidance(inputs, decision):
    import hashlib
    text = "SYNTHETIC_OPTIONAL_GUIDANCE"
    digest = hashlib.sha256(text.encode()).hexdigest()
    guidance = {"admission": "explicitly_enabled", "authority": "project", "resource_id": "fixture",
                "revision": "1", "content_hash": digest, "role": "optional", "token_count": None,
                "task_id": inputs["request"]["task_id"]}
    decision["execution_plan"].update(optional_guidance=[guidance], guidance_action="inject")
    inputs["catalog"] = {"schema_version": "1", "revision": "fixture", "resources": [{
        "resource_id": "fixture", "revision": "1", "content_hash": digest, "instructions": text,
        "admission": "explicitly_enabled", "domain": "fixture", "specialty": "fixture", "task_family": "fixture",
        "facets": [], "aliases": [], "source_occurrences": [], "conflicts": [], "rights": "synthetic",
        "benchmark_effort": None, "benchmark_protocol": None, "benchmark_split": None}]}


@pytest.mark.parametrize("case, expected", [
    ("completed", "guidance_scoped_to_task_prompt"),
    ("unavailable", "executor_unavailable"),
    ("identity_mismatch", "executor_identity_mismatch"),
    ("canceled", "launch_canceled"),
    ("raised", "launch_aborted"),
])
def test_deactivation_reports_the_host_limitation(tmp_path, case, expected):
    adapter, inputs, decision, kwargs, calls, _ = adapter_fixture(tmp_path)
    with_guidance(inputs, decision)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    fields = {"completed": {}, "unavailable": {"returncode": None, "available": False},
              "identity_mismatch": {"selected_model": "other"}, "canceled": {"interrupted": True}}

    def execute(spec, **_kwargs):
        if case == "raised":
            raise RuntimeError("synthetic executor failure")
        return result_for(**fields[case])

    if case == "raised":
        with pytest.raises(RuntimeError):
            adapter.launch(execute, spec_for(prepared))
    else:
        adapter.launch(execute, spec_for(prepared))
    drain(adapter)
    deactivated = [event["payload"] for event in delivered(calls)
                   if event["payload"].get("event_type") == "guidance_deactivated"]
    assert len(deactivated) == 1
    assert deactivated[0]["reason"] == expected

    # A lifecycle reason survives only as a closed deactivation code.
    report = fixture("ReportRequest")
    for field in ("harness_id", "execution_target_id"):
        report["envelope"][field] = report["event"]["task_id"]
    report["event"]["payload"] = {"kind": "lifecycle", "event_type": "started", "applied_plan_id": None,
                                  "reason": "PRIVATE free text"}
    assert adapter.sanitize_report(report)["event"]["payload"]["reason"] is None
    report["event"]["payload"].update(event_type="guidance_deactivated")
    assert adapter.sanitize_report(report)["event"]["payload"]["reason"] is None
    report["event"]["payload"].update(reason=expected)
    assert adapter.sanitize_report(report)["event"]["payload"]["reason"] == expected
    assert expected in DEACTIVATION_REASONS


# --- Item 4 (GAPS §3.4) ---------------------------------------------------------------------


def unspawnable(tmp_path):
    cli = JevDrillTransport((str(tmp_path / "missing" / "jevdrill-cli"),), tmp_path / "jev-state",
                            FIXTURES, json.loads((FIXTURES / "digests.json").read_text()))
    raised = []
    real = cli.call

    def call(command, payload, **options):
        try:
            return real(command, payload, **options)
        except BaseException as exc:
            raised.append(exc)
            raise

    cli.call = call
    return cli, raised


def disconnect_notices(notices, operation):
    return [n for n in notices if n.get("status") == "disconnected" and n.get("operation") == operation]


@pytest.mark.parametrize("entry", ["prepare", "discover"])
def test_route_disconnect_carries_advice(tmp_path, entry):
    adapter, inputs, _, kwargs, _, notices = adapter_fixture(tmp_path)
    adapter.transport, raised = unspawnable(tmp_path)
    with pytest.raises(OSError) as error:
        if entry == "prepare":
            adapter.prepare(mode="main", dry_run=False, **kwargs)
        else:
            objective = deepcopy(next(row["payload"] for row in load_rows("discovery.json")
                                      if row["accepted"] and row["contract"] == "DiscoveryInputs"))
            objective["envelope"].update({key: inputs["request"]["envelope"][key] for key in (
                "project_id", "workspace_id", "harness_id", "execution_target_id")})
            adapter.discover_objective(objective)
    assert type(error.value) is FileNotFoundError and error.value is raised[0]
    assert getattr(error.value, "resolution_advice", None) == disconnect_advice("route")
    assert disconnect_notices(notices, "route") == [{
        "kind": "transport_disposition", "status": "disconnected", "operation": "route",
        "resolution_advice": list(disconnect_advice("route"))}]


def test_report_disconnect_keeps_backoff_and_advises(tmp_path):
    adapter, _, _, kwargs, _, notices = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    report = fixture("ReportRequest")
    for field in ("harness_id", "execution_target_id"):
        report["envelope"][field] = report["event"]["task_id"]
    assert adapter.queue.enqueue(report) == "queued"
    adapter.transport, raised = unspawnable(tmp_path)
    assert adapter.flush() == "retry"
    assert raised and isinstance(raised[0], FileNotFoundError)
    with sqlite3.connect(adapter.queue.path) as db:
        rows = db.execute("SELECT attempts, retry_at, state FROM reports").fetchall()
    assert len(rows) == 1 and rows[0][0] == 1 and rows[0][1] > time.time() and rows[0][2] == "pending"
    assert disconnect_notices(notices, "report") == [{
        "kind": "transport_disposition", "status": "disconnected", "operation": "report",
        "resolution_advice": list(disconnect_advice("report"))}]
    executor_result = result_for(output="executor output")
    observed = adapter.launch(lambda spec, **_k: executor_result, spec_for(prepared))
    assert (observed.output, observed.returncode) == (executor_result.output, executor_result.returncode)
    assert not any(w["status"] == "delivery_failed" for w in adapter.delivery_warnings)


def test_non_transport_delivery_errors_stay_distinct(tmp_path):
    adapter, _, _, kwargs, _, notices = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    sanitize = adapter.queue.sanitize

    def failing(report):
        if report["event"]["payload"].get("event_type") == "completed":
            raise ValueError("synthetic sanitizer refusal")
        return sanitize(report)

    adapter.queue.sanitize = failing
    executor_result = result_for(output="executor output")
    assert adapter.launch(lambda spec, **_k: executor_result, spec_for(prepared)).output == "executor output"
    assert adapter.delivery_warnings[-1] == {"kind": "transport_disposition", "status": "delivery_failed"}
    assert all("resolution_advice" not in notice for notice in notices)


# --- Item 5, row 5b (GAPS §3.5) -------------------------------------------------------------


def test_operator_model_is_kept_through_launch(tmp_path):
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    decoy = deepcopy(inputs["inventory"]["candidates"][0])
    decoy.update(model_id="decoy-model")
    full = deepcopy(inputs)
    full["inventory"]["candidates"].append(decoy)

    def narrowed(_context):
        value = deepcopy(full)
        value["inventory"]["candidates"] = [c for c in value["inventory"]["candidates"] if c["model_id"] != "decoy-model"]
        return value

    adapter.inputs_for = narrowed
    operator = replace(kwargs["model_selection"], model="model-a", effort="high", source="user_override")
    prepared = adapter.prepare(mode="main", dry_run=False, **{**kwargs, "model_selection": operator})
    assert route_payloads(calls)[-1]["inventory"]["candidates"][0]["model_id"] == "model-a"
    assert len(route_payloads(calls)[-1]["inventory"]["candidates"]) == 1
    selection = prepared["model_selection"]
    assert (selection.model, selection.effort, selection.source) == ("model-a", "high", "user_override")
    launched = []
    result = adapter.launch(lambda spec, **_k: launched.append(spec) or result_for(), spec_for(prepared))
    assert [(s.selected_model, s.effective_effort) for s in launched] == [("model-a", "high")]
    run = result.jevdrill_execution_run
    assert run["applied_plan_id"] is not None
    drain(adapter)
    events = delivered(calls, run["execution_run_id"])
    assert [e["payload"].get("event_type") for e in events][:2] == ["started", "completed"]


# --- Item 6 (GAPS §3.6) ---------------------------------------------------------------------


def patched_clock(monkeypatch):
    now = [datetime.now(timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]

    monkeypatch.setattr(jevdrill_adapter, "datetime", Clock)
    return now


def expiring_fixture(tmp_path, monkeypatch, **options):
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path, **options)
    now = patched_clock(monkeypatch)
    decision["readiness"]["valid_until"] = (now[0] + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    return adapter, decision, kwargs, calls, now


def assert_refused_after_started(adapter, prepared, calls):
    launched = []
    refused = None
    try:
        adapter.launch(lambda spec, **_k: launched.append(spec) or result_for(), spec_for(prepared))
    except JevDrillUnavailable as exc:
        refused = exc
    assert launched == [], "the executor launched after readiness expired"
    assert refused is not None and "not enforceable" in str(refused)
    assert queued_event_types(adapter)[-2:] == ["started", "canceled"]
    drain(adapter)
    assert [e["payload"].get("event_type") for e in delivered(calls)][-2:] == ["started", "canceled"]


def test_readiness_expiring_in_a_final_callback_refuses_launch(tmp_path, monkeypatch):
    reached = []
    state = {}

    def verify(candidate, context):
        if "decision" in state:  # the launch-time call
            readiness = state["decision"]["readiness"]
            assert jevdrill_adapter._fresh({"verified_at": readiness["verified_at"],
                                            "expires_at": readiness["valid_until"]})
            reached.append(True)
            state["now"][0] += timedelta(hours=2)
        return True

    adapter, decision, kwargs, calls, now = expiring_fixture(tmp_path, monkeypatch, verify_candidate=verify)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    state.update(decision=decision, now=now)
    assert_refused_after_started(adapter, prepared, calls)
    assert reached == [True]


def test_readiness_expiring_during_the_started_write_refuses_launch(tmp_path, monkeypatch):
    adapter, _, kwargs, calls, now = expiring_fixture(tmp_path, monkeypatch)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    enqueue = adapter.queue.enqueue

    def slow_enqueue(report):
        disposition = enqueue(report)
        if report["event"]["payload"].get("event_type") == "started":
            now[0] += timedelta(hours=2)
        return disposition

    adapter.queue.enqueue = slow_enqueue
    assert_refused_after_started(adapter, prepared, calls)


def test_fresh_launch_reports_started_before_dispatch(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    seen = []
    adapter.launch(lambda spec, **_k: seen.append(queued_event_types(adapter)) or result_for(), spec_for(prepared))
    assert seen == [["started"]]


# --- Item 7 (GAPS §3.7) ---------------------------------------------------------------------


class Captured(Exception):
    pass


def recording_subprocess(argvs, popen=None):
    def record(argv, **_kwargs):
        argvs.append(list(argv))
        if popen is None:
            raise Captured()
        return popen(argv, **_kwargs)
    return SimpleNamespace(Popen=record, PIPE=subprocess.PIPE, DEVNULL=subprocess.DEVNULL,
                           TimeoutExpired=subprocess.TimeoutExpired, run=subprocess.run)


def plain_transport(tmp_path, program="raise AssertionError('must not start')\n"):
    child = tmp_path / "child.py"
    child.write_text(program)
    return JevDrillTransport((sys.executable, str(child)), tmp_path / "state", FIXTURES,
                             json.loads((FIXTURES / "digests.json").read_text()))


def test_budget_reserves_spawn_time(tmp_path, monkeypatch):
    clock = MonotonicClock()
    monkeypatch.setattr(jevdrill_adapter, "time", clock)
    argvs = []
    monkeypatch.setattr(jevdrill_adapter, "subprocess", recording_subprocess(argvs))
    cli = plain_transport(tmp_path)
    started_at = clock.monotonic() - 2.0  # 3000 ms remain on the parent deadline
    with pytest.raises(Captured):
        cli.call("notices", fixture("NoticeRequest"), started_at=started_at)
    assert len(argvs) == 1
    budget_ms = int(argvs[0][argvs[0].index("--remaining-budget-ms") + 1])
    assert budget_ms == 3000 - 250, "the child budget does not reserve the 250 ms spawn allowance"
    deadline = started_at + 5
    assert budget_ms / 1000 + 250 / 1000 <= deadline - clock.monotonic()
    assert getattr(jevdrill_adapter, "SPAWN_ALLOWANCE_MS", None) == 250


def test_near_zero_budget_never_spawns(tmp_path, monkeypatch):
    clock = MonotonicClock()
    monkeypatch.setattr(jevdrill_adapter, "time", clock)
    argvs = []
    monkeypatch.setattr(jevdrill_adapter, "subprocess", recording_subprocess(argvs))
    cli = plain_transport(tmp_path)
    for remaining_s in (0.2, 0.25):
        outcome = None
        try:
            cli.call("notices", fixture("NoticeRequest"), started_at=clock.monotonic() - 5 + remaining_s)
        except (TimeoutError, Captured) as exc:
            outcome = exc
        assert argvs == [], f"spawned with {remaining_s * 1000:.0f} ms left, within the reserve"
        assert isinstance(outcome, TimeoutError) and "before spawn" in str(outcome)


def test_over_reserve_spawn_is_bounded_by_the_parent_deadline(tmp_path, monkeypatch):
    children, handed = [], []

    def slow_popen(argv, **kwargs):
        child = subprocess.Popen(argv, **kwargs)
        children.append(child)
        time.sleep(0.4)  # startup forced past the 250 ms reserve
        handed.append(time.monotonic())
        return child

    argvs = []
    monkeypatch.setattr(jevdrill_adapter, "subprocess", recording_subprocess(argvs, slow_popen))
    cli = plain_transport(tmp_path, "import time\ntime.sleep(60)\n")
    begin = time.monotonic()
    started_at = begin - 3.0
    deadline = started_at + 5  # about 2 s remain, well over the reserve
    with pytest.raises(TimeoutError):
        cli.call("notices", fixture("NoticeRequest"), started_at=started_at)
    ended = time.monotonic()
    assert len(children) == 1, "the child was not started"
    assert handed[0] - begin > 0.25 and handed[0] < deadline
    assert deadline - 0.05 <= ended <= deadline + 1.0
    assert children[0].returncode is not None, "the started child was not reaped"


def test_delete_argv_has_no_budget_flag(tmp_path, monkeypatch):
    clock = MonotonicClock()
    monkeypatch.setattr(jevdrill_adapter, "time", clock)
    argvs = []
    monkeypatch.setattr(jevdrill_adapter, "subprocess", recording_subprocess(argvs))
    cli = plain_transport(tmp_path)
    task = str(uuid4())
    payload = {"schema_version": "1", "task_id": task, "scope": {
        "project_id": task, "workspace_id": task, "producer": task, "operation": "route"}}
    with pytest.raises(Captured):
        cli.call("delete", payload, started_at=clock.monotonic() - 4.9)
    assert argvs == [[*cli.argv, "--storage", str(cli.storage), "delete", "--task-id", payload["task_id"],
                      "--scope", json.dumps(payload["scope"])]]
    with pytest.raises(TimeoutError, match="before spawn"):
        cli.call("delete", payload, started_at=clock.monotonic() - 6)
    assert len(argvs) == 1


# --- Item 9 (GAPS §3.8) ---------------------------------------------------------------------


def declared_repo(tmp_path, envelope, *, harness=None, target=None):
    from phase_loop_test_utils import make_repo
    repo = make_repo(tmp_path)
    path = repo / ".jevdrill" / "harnesses.yaml"
    path.parent.mkdir()
    path.write_text(json.dumps({"schema_version": "1", "harnesses": [{
        "harness_id": harness or envelope["harness_id"],
        "execution_target_id": target or envelope["execution_target_id"],
        "declared_capabilities": ["text"], "access_routes": ["codex_cli"]}]}))
    return repo


@pytest.mark.parametrize("varied", ["harness", "target", "both"])
def test_undeclared_identity_makes_no_cli_request(tmp_path, varied):
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    other = {"harness": str(uuid4()) if varied in ("harness", "both") else None,
             "target": str(uuid4()) if varied in ("target", "both") else None}
    repo = declared_repo(tmp_path, inputs["request"]["envelope"], **other)
    refused = None
    try:
        adapter.prepare(mode="main", dry_run=False, **kwargs, repo=repo)
    except JevDrillUnavailable as exc:
        refused = exc
    assert calls == [], "a CLI request was made for an undeclared harness identity"
    assert refused is not None and "not declared" in str(refused)


def test_declared_identity_and_absent_file_still_route(tmp_path):
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    repo = declared_repo(tmp_path, inputs["request"]["envelope"])
    assert adapter.prepare(mode="main", dry_run=False, **kwargs, repo=repo)["model_selection"].model == "model-a"
    assert [command for command, _ in calls] == ["notices", "route"]
    (repo / ".jevdrill" / "harnesses.yaml").unlink()
    calls.clear()
    assert adapter.prepare(mode="main", dry_run=False, **kwargs, repo=repo)["model_selection"].model == "model-a"
    assert [command for command, _ in calls] == ["notices", "route"]


# --- Item 3 hook: run-bound explicit reports (JEV Drill consumer request) --------------------


def evaluation_payload(index):
    return {"kind": "evaluation", "check_results": {f"check-{index}": True}, "evaluator_ref": "synthetic",
            "rubric_revision": "1", "measurements": []}


def test_run_bound_reports_share_the_run_stream(tmp_path):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    identity, enqueue, counts = require(adapter, "run_event_identity", "enqueue_run_event", "run_report_counts")
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    decision_id = adapter.last_decision["details"]["routing_decision_id"]
    observed = []

    def execute(spec, **_k):
        # A hook reporting while the run executes shares the host's stream.
        run_id = next(iter(adapter._runs))
        observed.append(identity(run_id))
        enqueue(run_id, evaluation_payload("during"))
        return result_for()

    result = adapter.launch(execute, spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    assert observed[0] == {"task_id": kwargs_task(adapter, run_id), "routing_decision_id": decision_id,
                           "execution_run_id": run_id, "source_id": "agent-harness", "next_source_sequence": 1}
    after = identity(run_id)
    assert after["next_source_sequence"] == 4  # started, hook, terminal, usage

    threads = [threading.Thread(target=enqueue, args=(run_id, evaluation_payload(i))) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    drain(adapter)
    events = delivered(calls, run_id)
    assert [e["source_sequence"] for e in events] == list(range(10))
    assert len({e["source_id"] for e in events}) == 1
    assert {(e["task_id"], e["routing_decision_id"]) for e in events} == {(after["task_id"], decision_id)}
    assert [e["payload"].get("event_type") for e in events][:4] == ["started", None, "completed", None]
    assert counts(run_id) == {"queued": 10, "losses": {}}

    with pytest.raises(ValueError, match="non-lifecycle"):
        enqueue(run_id, {"kind": "lifecycle", "event_type": "completed", "applied_plan_id": None, "reason": None})
    with pytest.raises(KeyError):
        identity(str(uuid4()))


def kwargs_task(adapter, run_id):
    return adapter._runs[run_id]["request"]["task_id"]


def test_run_report_counts_track_entries_and_losses(tmp_path):
    adapter, inputs, _, kwargs, _, notices = adapter_fixture(tmp_path)
    _, enqueue, counts = require(adapter, "run_event_identity", "enqueue_run_event", "run_report_counts")
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    adapter.flush = lambda: "empty"  # keep every entry queued
    run_id = adapter.launch(lambda spec, **_k: result_for(), spec_for(prepared)).jevdrill_execution_run["execution_run_id"]
    assert counts(run_id) == {"queued": 3, "losses": {}}
    assert enqueue(run_id, evaluation_payload(0)) == "queued"
    assert counts(run_id) == {"queued": 4, "losses": {}}
    assert adapter.queue.status() == {"records": 4, "dispositions": {}}
    adapter.queue.MAX_RECORDS = 4
    assert enqueue(run_id, evaluation_payload(1)) == "overflow"
    envelope = inputs["request"]["envelope"]
    adapter.delete_task({"project_id": envelope["project_id"], "workspace_id": envelope["workspace_id"],
                         "producer": envelope["harness_id"], "operation": "route"}, inputs["request"]["task_id"])
    assert enqueue(run_id, evaluation_payload(2)) == "deleted"
    assert counts(run_id) == {"queued": 4, "losses": {"overflow": 1, "deleted": 1}}
    assert adapter.queue.status() == {"records": 0, "dispositions": {"overflow": 1, "deleted": 5}}
    assert [n["status"] for n in notices if n.get("kind") == "transport_disposition"] == ["overflow", "deleted"]
