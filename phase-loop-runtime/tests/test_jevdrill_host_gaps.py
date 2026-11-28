"""JEVHOST host gaps, adapter half (GAPS §3.1, §3.2, §3.4, §3.5 row 5b, §3.6-§3.8, item-3 hook).

Every test is synthetic: a fake or unspawnable CLI, no provider, model or live JEV call.
Tests that need an adapter interface absent from the base fail at an explicit availability
assertion naming it, so the base outcome is recorded separately from semantic failures.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from phase_loop_runtime import jevdrill_adapter, jevdrill_queue, windows_storage
from phase_loop_runtime.jevdrill_adapter import JevDrillTransport, JevDrillUnavailable
from phase_loop_runtime.launcher import LaunchResult
from jevdrill_fixture_values import load_rows
from test_jevdrill_adapter import FIXTURES, adapter_fixture, fixture


def seam(*names):
    """GAPS §3.0: a test-local seam import that fails at a named availability assertion."""
    try:
        from phase_loop_runtime import host_integration
    except ImportError:
        host_integration = None
    missing = [n for n in names if host_integration is None or not hasattr(host_integration, n)]
    assert not missing, "host_integration is unavailable: missing interface " + ", ".join(missing)
    values = [getattr(host_integration, n) for n in names]
    return values[0] if len(values) == 1 else values


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


def counting_executor(entries):
    def execute(spec, **_kwargs):
        entries.append(spec)
        return result_for()
    return execute


def test_spent_binding_never_falls_through_to_ordinary_launch(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)  # max_attempts=1
    entries = []
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    adapter.launch(counting_executor(entries), spec_for(prepared))
    refused = []
    for _ in range(2):  # a spent binding stays refused on retry
        try:
            adapter.launch(counting_executor(entries), spec_for(prepared))
        except JevDrillUnavailable as exc:
            refused.append(str(exc))
    assert len(entries) == 1, "a consumed or refused routed binding reached the executor again"
    assert refused == ["Routed launch binding was already used or refused"] * 2
    # A genuinely unrouted bundle carries no routing provenance and launches normally.
    unrouted = replace(kwargs["prompt_bundle"], body="unrouted work")
    adapter.launch(counting_executor(entries), SimpleNamespace(prompt_bundle=unrouted))
    assert len(entries) == 2


def rebuilt(bundle):
    from dataclasses import fields
    return type(bundle)(**{field.name: getattr(bundle, field.name) for field in fields(bundle)})


@pytest.mark.parametrize("state", ["pending", "consumed", "refused"])
def test_copied_routed_bundles_cannot_bypass_admission(tmp_path, state):
    verified = [True]
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path, verify_candidate=lambda *_a: verified[0])
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    original = prepared["prompt_bundle"]
    entries, outcomes = [], []

    def attempt(bundle):
        try:
            adapter.launch(counting_executor(entries), spec_for({**prepared, "prompt_bundle": bundle}))
            outcomes.append("launched")
        except JevDrillUnavailable as exc:
            outcomes.append(str(exc))

    if state == "pending":
        attempt(replace(original))  # a copy of a pending bundle takes that binding once
        expected_entries = 1
    elif state == "consumed":
        attempt(original)
        expected_entries = 1
    else:
        verified[0] = False
        attempt(original)  # refused at the launch-time identity check
        verified[0] = True
        expected_entries = 0
    for bundle in (original, replace(original), rebuilt(original)):
        attempt(bundle)
    assert len(entries) == expected_entries, f"a copied {state} routed bundle bypassed launch admission"
    assert outcomes[-3:] == ["Routed launch binding was already used or refused"] * 3


def test_identical_tasks_keep_their_own_authorization(tmp_path):
    env = routed_fixture(tmp_path, max_attempts=1)
    adapter = env.adapter
    prepared = {}
    for name in ("a", "b"):  # identical prompt, model and effort; different tasks
        env.current[0] = name
        prepared[name] = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    entries, outcomes = [], []
    for name in ("a", "a", "b"):
        try:
            result = adapter.launch(counting_executor(entries), spec_for(prepared[name]))
            outcomes.append((result.jevdrill_execution_run or {}).get("task_id", "unrouted dispatch"))
        except JevDrillUnavailable as exc:
            outcomes.append(str(exc))
    assert outcomes[1] == "Routed launch binding was already used or refused", (
        "a spent launch consumed another task's authorization")
    assert len(entries) == 2
    assert outcomes == [env.task("a")["request"]["task_id"], "Routed launch binding was already used or refused",
                        env.task("b")["request"]["task_id"]]


def test_reordered_reconstruction_stays_routed(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    kwargs["prompt_bundle"] = replace(kwargs["prompt_bundle"], bridge_skill_inventory=({"a": 1, "b": 2},))
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    original = prepared["prompt_bundle"]
    entries = []
    adapter.launch(counting_executor(entries), spec_for(prepared))
    reordered = replace(rebuilt(original), bridge_skill_inventory=({"b": 2, "a": 1},))
    assert reordered == original
    refused = None
    try:
        adapter.launch(counting_executor(entries), spec_for({**prepared, "prompt_bundle": reordered}))
    except JevDrillUnavailable as exc:
        refused = exc
    assert len(entries) == 1, "an equal reconstructed routed bundle skipped launch admission"
    assert refused is not None


def test_routing_id_without_a_live_binding_fails_closed(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    routing_id = getattr(prepared["prompt_bundle"], "routing_provenance", None)
    assert routing_id is not None, "prepare stamped no routing provenance on the bundle"
    entries, outcomes = [], []
    adapter.launch(counting_executor(entries), spec_for(prepared))
    for bundle in (prepared["prompt_bundle"],  # spent id
                   replace(prepared["prompt_bundle"], routing_provenance=str(uuid4()))):  # never issued
        try:
            adapter.launch(counting_executor(entries), spec_for({**prepared, "prompt_bundle": bundle}))
            outcomes.append("launched")
        except JevDrillUnavailable as exc:
            outcomes.append(str(exc))
    assert len(entries) == 1, "a routed id with no live binding was dispatched"
    assert outcomes == ["Routed launch binding was already used or refused"] * 2
    assert "routing_provenance" not in json.dumps(prepared["prompt_bundle"].to_json())


def linked_fixture(tmp_path, *, max_attempts=1, valid_until=None):
    adapter, inputs, decision, kwargs, calls, _ = adapter_fixture(tmp_path)
    inputs["request"]["hard_constraints"]["max_attempts"] = max_attempts
    if valid_until is not None:
        decision["readiness"]["valid_until"] = valid_until
    ref = {"discovery_id": str(uuid4()), "work_objective_id": str(uuid4()), "trace_digest": "a" * 64}
    adapter.queue.bind_objective(inputs["request"]["envelope"], ref)
    decision["details"]["discovery_ref"] = ref
    wrapper = {"schema_version": "2", "route_inputs": inputs, "discovery_ref": ref}
    routed = adapter.transport.call

    def call(command, payload, **options):
        if command == "inspect-discovery":
            calls.append((command, deepcopy(payload)))
            return {"schema_version": "1", "status": "selected_guidance", "details": dict(ref)}
        return routed(command, payload, **options)

    adapter.transport.call = call
    adapter.inputs_for = lambda _context: deepcopy(wrapper)
    return adapter, kwargs, calls


@pytest.mark.parametrize("case", ["slot_spent", "budget_expired"])
def test_linked_launch_checks_the_ledger_before_cli_contact(tmp_path, monkeypatch, case):
    clock = MonotonicClock()
    monkeypatch.setattr(jevdrill_adapter, "time", clock)
    adapter, kwargs, calls = linked_fixture(tmp_path)
    entries = []
    first = adapter.prepare(mode="main", dry_run=False, **kwargs)
    if case == "slot_spent":
        second = adapter.prepare(mode="main", dry_run=False, **kwargs)
        adapter.launch(counting_executor(entries), spec_for(first))
        target = second
    else:
        clock.advance_ms(5000)
        target = first
    contacted = len(calls)
    callbacks = []
    adapter.verify_candidate = lambda *_a: callbacks.append(True) or True
    refused = None
    try:
        adapter.launch(counting_executor(entries), spec_for(target))
    except JevDrillUnavailable as exc:
        refused = exc
    assert calls[contacted:] == [], "a spent or expired linked binding contacted the CLI"
    assert callbacks == [] and len(entries) == int(case == "slot_spent")
    assert refused is not None and "Retry budget is exhausted" in str(refused)


def test_reopened_ledger_rejects_an_old_generation(tmp_path):
    env = routed_fixture(tmp_path, max_attempts=1)
    adapter = env.adapter
    record, = require(adapter, "record_acceptance_outcome")
    entries = []
    prepared_a = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    prepared_b = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    result = adapter.launch(counting_executor(entries), spec_for(prepared_a))
    record(result.jevdrill_execution_run["execution_run_id"], passed=True, failure_class=None)
    prepared_c = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    refused = None
    try:
        adapter.launch(counting_executor(entries), spec_for(prepared_b))
    except JevDrillUnavailable as exc:
        refused = exc
    assert len(entries) == 1, "a binding from a closed ledger entry spent the reopened budget"
    assert refused is not None and "Retry record is closed" in str(refused)
    adapter.launch(counting_executor(entries), spec_for(prepared_c))
    assert len(entries) == 2


def test_refused_prepare_holds_no_ledger_slot(tmp_path, monkeypatch):
    env = routed_fixture(tmp_path)
    adapter = env.adapter
    monkeypatch.setattr(jevdrill_adapter, "RETRY_LEDGER_LIMIT", 1, raising=False)
    forged = fixture("RouteRequest")["retry_context"]
    forged["remaining_spend"] = None
    env.task("forged")["request"]["retry_context"] = forged
    refusals = []
    for name in ("forged", "deleted"):
        if name == "deleted":
            request = env.task(name)["request"]
            adapter.queue.delete_task(request["envelope"]["project_id"], request["envelope"]["workspace_id"],
                                      request["task_id"])
        env.current[0] = name
        try:
            adapter.prepare(mode="main", dry_run=False, **env.kwargs)
        except JevDrillUnavailable as exc:
            refusals.append(str(exc))
    assert len(refusals) == 2, "a forged or deleted task was routed as launchable"
    env.current[0] = "valid"
    try:
        prepared = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    except JevDrillUnavailable as exc:
        prepared = exc
    assert not isinstance(prepared, Exception), f"a refused prepare held the only ledger slot: {prepared}"


def test_pass_during_routing_cannot_open_a_new_generation(tmp_path):
    env = routed_fixture(tmp_path, max_attempts=2)
    adapter = env.adapter
    record, = require(adapter, "record_acceptance_outcome")
    first = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    run_id = adapter.launch(lambda spec, **_k: result_for(), spec_for(first)).jevdrill_execution_run["execution_run_id"]
    routed = adapter.transport.call

    def call(command, payload, **options):
        if command == "route":  # the verdict lands between route admission and commit
            record(run_id, passed=True, failure_class=None)
        return routed(command, payload, **options)

    adapter.transport.call = call
    outcome = None
    try:
        outcome = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    except JevDrillUnavailable as exc:
        outcome = exc
    assert isinstance(outcome, JevDrillUnavailable), "a prepare admitted against a closed entry was published"
    assert "closed during routing" in str(outcome)
    assert adapter._ledger == {} and not adapter._pending


def test_pass_before_linked_revalidation_prevents_cli_contact(tmp_path):
    adapter, kwargs, calls = linked_fixture(tmp_path, max_attempts=2)
    record, = require(adapter, "record_acceptance_outcome")
    first = adapter.prepare(mode="main", dry_run=False, **kwargs)
    run_id = adapter.launch(lambda spec, **_k: result_for(), spec_for(first)).jevdrill_execution_run["execution_run_id"]
    second = adapter.prepare(mode="main", dry_run=False, **kwargs)
    bound = adapter.queue.objective_bound

    def verdict_then_bound(*args):
        record(run_id, passed=True, failure_class=None)  # after the early check, before the CLI call
        return bound(*args)

    adapter.queue.objective_bound = verdict_then_bound
    contacted, entries, refused = len(calls), [], None
    try:
        adapter.launch(counting_executor(entries), spec_for(second))
    except JevDrillUnavailable as exc:
        refused = exc
    assert calls[contacted:] == [], "a binding closed before linked revalidation contacted the CLI"
    assert entries == [] and refused is not None and "Retry record is closed" in str(refused)


def test_failed_linked_binding_write_leaves_no_ledger_slot(tmp_path, monkeypatch):
    adapter, kwargs, _ = linked_fixture(tmp_path)
    monkeypatch.setattr(jevdrill_adapter, "RETRY_LEDGER_LIMIT", 1, raising=False)
    bind_task = adapter.queue.bind_task
    failures = [OSError("synthetic binding write failure")]

    def failing_bind_task(*args):
        if failures:
            raise failures.pop()
        return bind_task(*args)

    adapter.queue.bind_task = failing_bind_task
    with pytest.raises(OSError, match="binding write"):
        adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert getattr(adapter, "_ledger", {}) == {}, "a failed prepare holds a ledger slot"
    assert not adapter._pending
    assert adapter.prepare(mode="main", dry_run=False, **kwargs)["model_selection"].model == "model-a"


class OrderedLock:
    """Records whether it is entered while the other lock of a pair is held."""

    def __init__(self, lock, name, held, violations, forbidden_under):
        self._lock, self.name, self.held = lock, name, held
        self.violations, self.forbidden_under = violations, forbidden_under

    def __enter__(self):
        if self.held.get(self.forbidden_under) and not self.held.get(self.name):
            self.violations.append(f"{self.name} acquired while holding {self.forbidden_under}")
        value = self._lock.__enter__()
        self.held[self.name] = self.held.get(self.name, 0) + 1
        return value

    def __exit__(self, *exc):
        self.held[self.name] -= 1
        return self._lock.__exit__(*exc)


def test_report_lock_is_taken_before_the_ledger_lock(tmp_path, monkeypatch):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    held, violations = {}, []
    for name, forbidden_under in (("_report_lock", "_ledger_lock"), ("_ledger_lock", "_report_lock_unused")):
        monkeypatch.setattr(adapter, name, OrderedLock(getattr(adapter, name, threading.RLock()), name, held,
                                                       violations, forbidden_under), raising=False)
    adapter.launch(lambda spec, **_k: result_for(), spec_for(prepared))
    assert violations == [], "the report lock was acquired while holding the ledger lock"


def test_flush_notices_leave_the_queue_transaction(tmp_path):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    inbox = {"schema_version": "1", "notices": [{"kind": "synthetic_notice"}]}
    routed = adapter.transport.call
    adapter.transport.call = lambda command, payload, **o: (
        deepcopy(inbox) if command == "notices" else routed(command, payload, **o))
    depth, seen = [0], []
    transaction = adapter.queue._transaction
    from contextlib import contextmanager

    @contextmanager
    def tracked():
        with transaction() as db:
            depth[0] += 1
            try:
                yield db
            finally:
                depth[0] -= 1

    adapter.queue._transaction = tracked
    adapter.notice_sink = lambda notice: seen.append(depth[0])
    report = fixture("ReportRequest")
    for field in ("harness_id", "execution_target_id"):
        report["envelope"][field] = report["event"]["task_id"]
    adapter.queue.enqueue(report)
    adapter.flush()
    assert seen and all(level == 0 for level in seen), "a notice callback ran inside the queue write transaction"


class ArmedLock:
    """A lock that runs ``on_enter`` the first time it is entered after being armed."""

    def __init__(self, lock, on_enter):
        self._lock, self._on_enter, self.armed = lock, on_enter, False

    def __enter__(self):
        if self.armed:
            self.armed = False
            self._on_enter()
        return self._lock.__enter__()

    def __exit__(self, *exc):
        return self._lock.__exit__(*exc)

    def acquire(self, *args, **kwargs):
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        return self._lock.release()


@pytest.mark.parametrize("lock", ["ledger", "report"])
def test_lock_wait_cannot_outlive_readiness(tmp_path, monkeypatch, lock):
    adapter, inputs, decision, kwargs, calls, _ = adapter_fixture(tmp_path)
    with_guidance(inputs, decision)
    now = patched_clock(monkeypatch)
    decision["readiness"]["valid_until"] = (now[0] + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    name = "_ledger_lock" if lock == "ledger" else "_report_lock"
    armed = ArmedLock(getattr(adapter, name, threading.RLock()),
                      lambda: now.__setitem__(0, now[0] + timedelta(hours=2)))
    monkeypatch.setattr(adapter, name, armed, raising=False)
    enqueue = adapter.queue.enqueue

    def arm_after_started(report):
        disposition = enqueue(report)
        if report["event"]["payload"].get("event_type") == "started":
            armed.armed = True
        return disposition

    adapter.queue.enqueue = arm_after_started
    entries = []
    try:
        adapter.launch(counting_executor(entries), spec_for(prepared))
    except JevDrillUnavailable:
        pass
    assert entries == [], "the executor was dispatched after readiness expired during a lock wait"
    assert queued_event_types(adapter) == ["started", "canceled", "guidance_deactivated"]
    drain(adapter)
    deactivated = [e["payload"]["reason"] for e in delivered(calls)
                   if e["payload"].get("event_type") == "guidance_deactivated"]
    assert deactivated == ["launch_canceled"]
    assert all(not entry["attempts"] for entry in adapter._ledger.values()), "a refused launch was charged"


def test_competing_launches_enter_the_executor_once(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)  # max_attempts=1
    specs = [spec_for(adapter.prepare(mode="main", dry_run=False, **kwargs)) for _ in range(2)]
    barrier = threading.Barrier(2)
    entries = []

    def compete(spec):
        barrier.wait(timeout=5)
        try:
            adapter.launch(counting_executor(entries), spec)
        except JevDrillUnavailable as exc:
            return str(exc)
        return "launched"

    with ThreadPoolExecutor(max_workers=2) as pool:
        launches = [pool.submit(compete, spec) for spec in specs]
        outcomes = [launch.result(timeout=30) for launch in launches]
    assert len(entries) == 1, "two competing launches both reached the executor"
    assert sorted(outcomes) == ["Retry budget is exhausted", "launched"]


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


@pytest.mark.parametrize("case, expected, expected_terminal", [
    ("completed", "guidance_scoped_to_task_prompt", "completed"),
    ("timed_out", "guidance_scoped_to_task_prompt", "failed"),
    ("stalled", "guidance_scoped_to_task_prompt", "failed"),
    ("unavailable", "executor_unavailable", "failed"),
    ("identity_mismatch", "executor_identity_mismatch", "completed"),
    ("canceled", "launch_canceled", "canceled"),
    ("raised", "launch_aborted", "failed"),
])
def test_deactivation_reports_the_host_limitation(tmp_path, case, expected, expected_terminal):
    adapter, inputs, decision, kwargs, calls, _ = adapter_fixture(tmp_path)
    with_guidance(inputs, decision)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    fields = {"completed": {}, "timed_out": {"returncode": None, "timed_out": True},
              "stalled": {"returncode": None, "stalled": True},
              "unavailable": {"returncode": None, "available": False},
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
    events = [event["payload"] for event in delivered(calls)]
    lifecycle_types = [payload["event_type"] for payload in events if payload.get("kind") == "lifecycle"]
    assert lifecycle_types == ["started", expected_terminal, "guidance_deactivated"]
    deactivated = [payload for payload in events if payload.get("event_type") == "guidance_deactivated"]
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
    assert expected in seam("DEACTIVATION_REASONS")


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
    assert getattr(error.value, "resolution_advice", None) == seam("disconnect_advice")("route")
    assert disconnect_notices(notices, "route") == [{
        "kind": "transport_disposition", "status": "disconnected", "operation": "route",
        "resolution_advice": list(seam("disconnect_advice")("route"))}]


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
        "resolution_advice": list(seam("disconnect_advice")("report"))}]
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


@pytest.mark.parametrize("when", ["during_discovery_recheck", "during_started_write"])
def test_readiness_expiring_before_discovery_linked_launch_refuses_launch(tmp_path, monkeypatch, when):
    now = patched_clock(monkeypatch)
    valid_until = (now[0] + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    adapter, kwargs, calls = linked_fixture(tmp_path, valid_until=valid_until)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    calls_before_launch = len(calls)
    if when == "during_discovery_recheck":
        call = adapter.transport.call

        def slow_inspect(command, payload, **options):
            response = call(command, payload, **options)
            if command == "inspect-discovery":
                now[0] += timedelta(hours=2)
            return response

        adapter.transport.call = slow_inspect
        entries = []
        refused = None
        try:
            adapter.launch(counting_executor(entries), spec_for(prepared))
        except JevDrillUnavailable as exc:
            refused = exc
        assert entries == [], "the discovery-linked executor launched after readiness expired"
        assert refused is not None and "not enforceable" in str(refused)
        assert queued_event_types(adapter) == []
    else:
        enqueue = adapter.queue.enqueue
        inspect_before_started = []

        def slow_enqueue(report):
            if report["event"]["payload"].get("event_type") == "started":
                inspect_before_started.append(
                    any(command == "inspect-discovery" for command, _ in calls[calls_before_launch:])
                )
            disposition = enqueue(report)
            if report["event"]["payload"].get("event_type") == "started":
                now[0] += timedelta(hours=2)
            return disposition

        adapter.queue.enqueue = slow_enqueue
        assert_refused_after_started(adapter, prepared, calls)
        assert inspect_before_started == [True], "launch-time inspect-discovery did not run before started enqueue"
    assert any(command == "inspect-discovery" for command, _ in calls[calls_before_launch:])
    assert all(not entry["attempts"] for entry in adapter._ledger.values()), "a refused launch was charged"


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
    expected_budget_ms = 3000 - 250
    assert argvs == [[*cli.argv, "--storage", str(cli.storage),
                      "--remaining-budget-ms", str(expected_budget_ms), "notices"]]
    assert argvs[0].count("--remaining-budget-ms") == 1
    budget_ms = int(argvs[0][argvs[0].index("--remaining-budget-ms") + 1])
    assert budget_ms == expected_budget_ms, "the child budget does not reserve the 250 ms spawn allowance"
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
    clock = MonotonicClock()
    monkeypatch.setattr(jevdrill_adapter, "time", clock)
    children, waits, handed = [], [], []

    class Handle:
        """The real child behind a handle whose timed wait reports its timeout and expires."""

        def __init__(self, child):
            self._child = child

        def __getattr__(self, name):
            return getattr(self._child, name)

        def wait(self, timeout=None):
            if timeout is None:
                return self._child.wait()
            waits.append(timeout)
            raise subprocess.TimeoutExpired(self._child.args, timeout)

    def slow_popen(argv, **kwargs):
        child = subprocess.Popen(argv, **kwargs)
        children.append(child)
        clock.advance_ms(400)  # startup forced past the 250 ms reserve, on the controlled clock
        handed.append(clock.monotonic())
        return Handle(child)

    argvs = []
    monkeypatch.setattr(jevdrill_adapter, "subprocess", recording_subprocess(argvs, slow_popen))
    cli = plain_transport(tmp_path, "import time\ntime.sleep(60)\n")
    started_at = clock.monotonic() - 3.0
    deadline = started_at + 5  # 2000 ms remain, well over the reserve
    try:
        with pytest.raises(TimeoutError, match="exceeded deadline"):
            cli.call("notices", fixture("NoticeRequest"), started_at=started_at)
        assert len(children) == 1, "the child was not started"
        assert handed[0] < deadline
        # The parent waits only until its original deadline, never longer.
        assert waits == [pytest.approx(deadline - handed[0])] and waits[0] <= deadline - handed[0]
        assert children[0].returncode is not None, "the started child was not reaped"
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


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


def report_type(event):
    payload = event["payload"]
    return payload.get("event_type", payload["kind"])


def test_run_bound_reports_share_the_run_stream(tmp_path, monkeypatch):
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    identity, enqueue, counts = require(adapter, "run_event_identity", "enqueue_run_event", "run_report_counts")
    active_ids, = require(adapter, "active_execution_run_ids")
    task_id = inputs["request"]["task_id"]
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    decision_id = adapter.last_decision["details"]["routing_decision_id"]
    entered = []  # (sequence, kind) in the order reports reach the queue
    enqueue_queue = adapter.queue.enqueue
    flush = adapter.flush
    adapter.flush = lambda: "empty"  # inspect durable reports before delivery

    def ordered_enqueue(report):
        entered.append((report["event"]["source_sequence"], report_type(report["event"])))
        return enqueue_queue(report)

    adapter.queue.enqueue = ordered_enqueue
    observed, hooks = [], []
    ready = threading.Barrier(2, timeout=5)

    def hook(run_id, index):
        if index == 0:
            ready.wait()
        return enqueue(run_id, evaluation_payload(index))

    def execute(spec, **_k):
        run_id, = active_ids(task_id)
        observed.append(identity(run_id))
        # Hooks race the host's own terminal and usage reports after the executor returns.
        hooks.extend(pool.submit(hook, run_id, i) for i in range(6))
        ready.wait()
        return result_for()

    report = adapter._report

    def report_then_hook(binding, event_type=None, **options):
        disposition = report(binding, event_type, **options)
        if event_type == "completed":
            worker = pool.submit(hook, binding["run_id"], 6)
            hooks.append(worker)
            assert worker.result(timeout=5) == "queued"
        return disposition

    monkeypatch.setattr(adapter, "_report", report_then_hook)
    final_slot = threading.Barrier(2, timeout=5)

    def compete_for_slot(run_id, index):
        final_slot.wait()
        return hook(run_id, index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = adapter.launch(execute, spec_for(prepared))
        run_id = result.jevdrill_execution_run["execution_run_id"]
        assert [future.result(timeout=5) for future in hooks] == ["queued"] * 7
        adapter.queue.MAX_RECORDS = 11
        after_launch = {i: pool.submit(compete_for_slot, run_id, i) for i in (7, 8)}
        dispositions = {i: future.result(timeout=5) for i, future in after_launch.items()}
    assert sorted(dispositions.values()) == ["overflow", "queued"]
    queued_after_launch, = [i for i, disposition in dispositions.items() if disposition == "queued"]
    assert observed[0] == {"task_id": task_id, "routing_decision_id": decision_id,
                           "execution_run_id": run_id, "source_id": "agent-harness", "next_source_sequence": 1}
    # Enqueue order, before any sorting, is sequence order, with host and hook interleaved.
    assert [sequence for sequence, _ in entered] == list(range(12))
    assert identity(run_id)["next_source_sequence"] == 12
    assert counts(run_id) == {"queued": 11, "losses": {"overflow": 1}}
    assert adapter.queue.status() == {"records": 11, "dispositions": {"overflow": 1}}
    adapter.flush = flush
    drain(adapter)
    events = delivered(calls, run_id)
    assert [(event["source_sequence"], report_type(event)) for event in events] == entered[:-1]
    assert [report_type(event) for event in events if report_type(event) != "evaluation"] == [
        "started", "completed", "usage",
    ]
    evaluations = [e["payload"]["check_results"] for e in events if report_type(e) == "evaluation"]
    assert {tuple(checks.items()) for checks in evaluations} == {
        ((hashlib.sha256(f"check-{i}".encode()).hexdigest(), True),) for i in (*range(7), queued_after_launch)
    }
    assert report_type(events[-1]) == "evaluation"
    terminal_evaluation, = [e for e in events if e["payload"].get("check_results") == {
        hashlib.sha256(b"check-6").hexdigest(): True,
    }]
    completed, = [e for e in events if report_type(e) == "completed"]
    usage, = [e for e in events if report_type(e) == "usage"]
    assert completed["source_sequence"] < terminal_evaluation["source_sequence"] < usage["source_sequence"]
    assert len({e["source_id"] for e in events}) == 1
    assert {(e["task_id"], e["routing_decision_id"]) for e in events} == {(observed[0]["task_id"], decision_id)}
    assert adapter.queue.status() == {"records": 0, "dispositions": {"overflow": 1}}


def test_run_bound_report_refusals_leave_counts_unchanged(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    result = adapter.launch(lambda spec, **_k: result_for(), spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    counts_before = adapter.run_report_counts(run_id)
    queue_before = adapter.queue.status()
    with pytest.raises(ValueError, match="non-lifecycle"):
        adapter.enqueue_run_event(run_id, {"kind": "lifecycle", "event_type": "completed"})
    assert adapter.run_report_counts(run_id) == counts_before
    with pytest.raises(KeyError):
        adapter.enqueue_run_event(str(uuid4()), evaluation_payload(0))
    assert adapter.run_report_counts(run_id) == counts_before
    assert adapter.queue.status() == queue_before


@pytest.mark.parametrize("storage", ("native" if os.name == "nt" else "modeled",))
@pytest.mark.parametrize(("stage", "kinds"), [
    ("executor", ["started", "evaluation", "completed", "usage"]),
    ("after_terminal", ["started", "completed", "evaluation", "usage"]),
    ("after_launch", ["started", "completed", "usage", "evaluation"]),
])
def test_windows_run_bound_report_at_launch_stage(tmp_path, monkeypatch, storage, stage, kinds):
    if storage == "modeled":
        model_windows_queue_storage(monkeypatch)
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    task_id = inputs["request"]["task_id"]
    flush = adapter.flush
    adapter.flush = lambda: "empty"
    hooks = []

    def queue_hook(run_id, *, active):
        assert adapter.active_execution_run_ids(task_id) == ((run_id,) if active else ())
        worker = pool.submit(adapter.enqueue_run_event, run_id, evaluation_payload(0))
        hooks.append(worker)
        assert worker.result(timeout=5) == "queued"

    def execute(spec, **_k):
        if stage == "executor":
            run_id, = adapter.active_execution_run_ids(task_id)
            queue_hook(run_id, active=True)
        return result_for()

    # Run the post-terminal hook after the real report call returns and releases
    # the report lock, with the objective guard still held.
    report = adapter._report

    def report_then_hook(binding, event_type=None, **options):
        disposition = report(binding, event_type, **options)
        if stage == "after_terminal" and event_type == "completed":
            assert disposition == "queued"
            queue_hook(binding["run_id"], active=False)
        return disposition

    monkeypatch.setattr(adapter, "_report", report_then_hook)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = adapter.launch(execute, spec_for(prepared))
        run_id = result.jevdrill_execution_run["execution_run_id"]
        if stage == "after_launch":
            queue_hook(run_id, active=False)
        assert [worker.result(timeout=5) for worker in hooks] == ["queued"]
    assert adapter.delivery_warnings == []
    assert adapter.run_report_counts(run_id) == {"queued": 4, "losses": {}}
    assert adapter.queue.status() == {"records": 4, "dispositions": {}}
    adapter.flush = flush
    drain(adapter)
    assert [(event["source_sequence"], report_type(event)) for event in delivered(calls, run_id)] == list(enumerate(kinds))
    assert adapter.queue.status() == {"records": 0, "dispositions": {}}


def model_windows_queue_storage(monkeypatch):
    """Exercise the Windows queue path with POSIX files and exclusive directory bindings."""
    opened = {}

    class BoundDirectory:
        _check_deadline = windows_storage.BoundDirectory._check_deadline

        def __init__(self, path, *, create_private, deadline=None):
            assert create_private
            if path in opened:
                raise PermissionError("Modeled Windows directory sharing violation")
            self.path, self.deadline = path, deadline
            path.mkdir(parents=True, exist_ok=True)
            opened[path] = self
            self.flush()

        def open_record(self, name, *, create):
            assert opened[self.path] is self
            flags = os.O_RDWR | os.O_CREAT if create else os.O_RDONLY
            return os.open(self.path / name, flags, 0o600)

        def flush(self):
            assert opened[self.path] is self
            self._check_deadline()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            assert opened.pop(self.path) is self

    monkeypatch.setattr(jevdrill_queue, "os", SimpleNamespace(name="nt", close=os.close, fsync=os.fsync))
    monkeypatch.setattr(windows_storage, "BoundDirectory", BoundDirectory)
    return opened


def test_windows_objective_binding_outlives_borrowed_transaction(tmp_path, monkeypatch):
    opened = model_windows_queue_storage(monkeypatch)
    q = jevdrill_queue.ReportQueue(tmp_path / "private" / "queue.sqlite", sanitize=deepcopy)
    published, exit_guard, teardown, borrowing, finish = (threading.Event() for _ in range(5))
    storage_lock = q._storage_lock
    guard_thread = None

    class ObserveTeardown:
        acquire = storage_lock.acquire
        release = storage_lock.release

        def __enter__(self):
            if threading.get_ident() == guard_thread:
                if storage_lock.acquire(blocking=False):
                    storage_lock.release()
                    pytest.fail("The borrower did not hold the storage lock until transaction exit")
                teardown.set()
            return storage_lock.__enter__()

        def __exit__(self, *exc):
            return storage_lock.__exit__(*exc)

    monkeypatch.setattr(q, "_storage_lock", ObserveTeardown())

    def guard():
        nonlocal guard_thread
        guard_thread = threading.get_ident()
        with q.objective_guard():
            published.set()
            assert exit_guard.wait(10)

    def borrow():
        with q._transaction():
            borrowing.set()
            assert finish.wait(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(guard)
        assert published.wait(5)
        binding = opened[q.path.parent]
        borrower = pool.submit(borrow)
        try:
            assert borrowing.wait(5)
            exit_guard.set()
            assert teardown.wait(5)
            assert opened[q.path.parent] is binding
        finally:
            finish.set()
            exit_guard.set()
            borrower.result(timeout=5)
            holder.result(timeout=5)
        assert opened == {}
        assert pool.submit(q.status).result(timeout=5)["records"] == 0
    assert opened == {}


def test_nested_windows_objective_guard_preserves_outer_binding(tmp_path, monkeypatch):
    opened = model_windows_queue_storage(monkeypatch)
    q = jevdrill_queue.ReportQueue(tmp_path / "private" / "queue.sqlite", sanitize=deepcopy)
    with q.objective_guard():
        binding = opened[q.path.parent]
        with pytest.raises(RuntimeError, match="Nested Windows objective guard"):
            with q.objective_guard():
                pytest.fail("Nested guard admitted work")
        assert q._objective_directory is binding
        assert q.status()["records"] == 0
    assert opened == {}


def test_windows_queue_transaction_bounds_storage_lock_wait(tmp_path, monkeypatch):
    opened = model_windows_queue_storage(monkeypatch)
    q = jevdrill_queue.ReportQueue(tmp_path / "private" / "queue.sqlite", sanitize=deepcopy)

    def busy(*, timeout):
        assert timeout == 30
        return False

    monkeypatch.setattr(q, "_storage_lock", SimpleNamespace(acquire=busy))
    with pytest.raises(TimeoutError, match="Report queue storage lock deadline expired"):
        q.status()
    assert opened == {}


def test_run_reports_outlive_storage_admission_deadline(tmp_path, monkeypatch):
    if os.name != "nt":
        model_windows_queue_storage(monkeypatch)
    clock = MonotonicClock()
    monkeypatch.setattr(jevdrill_queue, "time", clock)
    monkeypatch.setattr(windows_storage, "time", clock)
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)

    def execute(spec, **_k):
        clock.advance_ms(6000)
        return result_for()

    result = adapter.launch(execute, spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    assert adapter.delivery_warnings == []
    assert adapter.run_report_counts(run_id) == {"queued": 3, "losses": {}}
    assert delivered(calls, run_id), "launch should automatically flush"
    drain(adapter)
    assert [(event["source_sequence"], report_type(event)) for event in delivered(calls, run_id)] == [
        (0, "started"), (1, "completed"), (2, "usage"),
    ]
    assert adapter.queue.status() == {"records": 0, "dispositions": {}}


@pytest.mark.parametrize("committed", [False, True])
def test_run_bound_storage_error_does_not_reuse_sequence(tmp_path, monkeypatch, committed):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    result = adapter.launch(lambda spec, **_k: result_for(), spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    enqueue = adapter.queue.enqueue
    failure = OSError("synthetic queue storage error")
    counts_before = adapter.run_report_counts(run_id)
    sequence_before = adapter.run_event_identity(run_id)["next_source_sequence"]

    def fail(report):
        if committed:
            assert enqueue(report) == "queued"
        raise failure

    with monkeypatch.context() as local:
        local.setattr(adapter.queue, "enqueue", fail)
        with pytest.raises(OSError) as raised:
            adapter.enqueue_run_event(run_id, evaluation_payload(0))
        assert raised.value is failure

    assert adapter.run_event_identity(run_id)["next_source_sequence"] == sequence_before + 1
    assert adapter.run_report_counts(run_id) == counts_before
    assert adapter.enqueue_run_event(run_id, evaluation_payload(1)) == "queued"
    assert adapter.run_report_counts(run_id) == {"queued": 4, "losses": {}}
    drain(adapter)
    assert [event["source_sequence"] for event in delivered(calls, run_id)] == (
        [0, 1, 2, 3, 4] if committed else [0, 1, 2, 4]
    )


def test_active_execution_run_ids_are_scoped_to_the_task(tmp_path):
    env = routed_fixture(tmp_path)
    adapter = env.adapter
    active_ids, = require(adapter, "active_execution_run_ids")
    task_id = env.task("a")["request"]["task_id"]
    other_task_id = env.task("b")["request"]["task_id"]
    prepared = adapter.prepare(mode="main", dry_run=False, **env.kwargs)
    assert active_ids(task_id) == ()
    observed = []

    def execute(spec, **_k):
        observed.append(active_ids(task_id))
        assert active_ids(other_task_id) == ()
        return result_for()

    result = adapter.launch(execute, spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    assert observed == [(run_id,)]
    assert active_ids(task_id) == ()
    assert adapter.run_event_identity(run_id)["task_id"] == task_id


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


@pytest.mark.parametrize("expected", ["queued", "deleted", "duplicate", "conflict", "overflow"])
def test_run_bound_report_disposition_matches_durable_queue_and_counts(tmp_path, monkeypatch, expected):
    adapter, inputs, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    adapter.flush = lambda: "empty"
    result = adapter.launch(lambda spec, **_k: result_for(), spec_for(prepared))
    run_id = result.jevdrill_execution_run["execution_run_id"]
    queue = adapter.queue
    enqueue = queue.enqueue

    def durable_reports():
        with queue._transaction() as db:
            return {row["event"]: json.loads(row["payload"]) for row in db.execute("SELECT event, payload FROM reports")}

    if expected == "deleted":
        request = inputs["request"]
        queue.delete_task(request["envelope"]["project_id"], request["envelope"]["workspace_id"], request["task_id"])
    if expected == "overflow":
        queue.MAX_RECORDS = 3

    # A hook normally generates a fresh event ID. Seed the real queue with that
    # ID just before enqueue to exercise its duplicate and conflict paths.
    before = None
    event_id = None

    def enqueue_with_setup(report):
        nonlocal before, event_id
        event_id = report["event"]["event_id"]
        if expected in ("duplicate", "conflict"):
            seed = deepcopy(report)
            if expected == "conflict":
                seed["event"]["payload"] = evaluation_payload(99)
            assert enqueue(seed) == "queued"
        before = durable_reports()
        return enqueue(report)

    monkeypatch.setattr(queue, "enqueue", enqueue_with_setup)
    assert adapter.enqueue_run_event(run_id, evaluation_payload(0)) == expected
    after = durable_reports()
    if expected == "queued":
        assert after.keys() - before.keys() == {event_id}
        entry = after.pop(event_id)
        assert entry["event"]["execution_run_id"] == run_id
        assert entry["event"]["source_sequence"] == 3
        assert entry["event"]["payload"]["kind"] == "evaluation"
        assert adapter.run_report_counts(run_id) == {"queued": 4, "losses": {}}
    else:
        assert adapter.run_report_counts(run_id) == {"queued": 3, "losses": {expected: 1}}
    assert after == before


# --- macOS leased refusal observation (Consiliency/jevdrill#153) ----------------------------


_FORWARD_AUDIT_EVENTS = frozenset({
    "subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn", "os.system",
    "os.fork", "os.forkpty", "pty.fork", "_posixsubprocess.fork_exec",
    "_thread.start_new_thread", "_thread.start_joinable_thread",
    "seat_test.fork_exec", "seat_test.fork", "seat_test.forkpty", "seat_test.pty_fork",
})
_FORWARD_AUDIT_PREFIXES = ("socket.", "http.client.", "urllib.", "ftplib.", "smtplib.")


_MACOS_LEASE_AUDIT_CHILD = """
import json, os, socket, subprocess, sys, threading
from pathlib import Path

FORWARD_EVENTS = set(json.loads(sys.argv[1]))
FORWARD_PREFIXES = tuple(json.loads(sys.argv[2]))
entry_point = sys.argv[3]
work_dir = Path(sys.argv[4])

observed = []
mode = ["off"]  # "off" | "record" | "reject"

def audit(event, args):
    if mode[0] != "off" and (event in FORWARD_EVENTS or event.startswith(FORWARD_PREFIXES)):
        observed.append(event)
        if mode[0] == "reject":
            raise RuntimeError(f"forbidden forward during leased macOS refusal: {event}")

sys.addaudithook(audit)

if os.name == "posix":
    import _posixsubprocess
    import pty

    def _wrap_fork(original, event):
        def audited(*args, **kwargs):
            sys.audit(event, *args)
            return original(*args, **kwargs)
        return audited

    _posixsubprocess.fork_exec = _wrap_fork(_posixsubprocess.fork_exec, "seat_test.fork_exec")
    os.fork = _wrap_fork(os.fork, "seat_test.fork")
    os.forkpty = _wrap_fork(os.forkpty, "seat_test.forkpty")
    pty.fork = _wrap_fork(pty.fork, "seat_test.pty_fork")

# Positive control: prove the audit observer records process, socket, and thread starts.
mode[0] = "record"
try:
    subprocess.run([sys.executable, "-c", "pass"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(("127.0.0.1", port))
            conn, _ = listener.accept()
            conn.close()
    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join(timeout=5)
finally:
    mode[0] = "off"

control_events = sorted(set(observed))

from phase_loop_runtime import launcher
from phase_loop_runtime.launcher import LaunchSpec
from phase_loop_runtime.models import InjectionMetadata, PromptBundle

class UnusedAuthority:
    def fileno(self):
        raise AssertionError("lease must not be transferred")

marker = work_dir / "must-not-start"
if entry_point == "launch_with_spec":
    child = work_dir / "codex"
    child.write_text(
        "#!" + sys.executable + "\\n"
        "from pathlib import Path\\n"
        f"Path({str(marker)!r}).touch()\\n",
        encoding="utf-8",
    )
    child.chmod(0o700)
    os.environ["PATH"] = str(work_dir) + os.pathsep + os.environ.get("PATH", "")
    bundle = PromptBundle("workflow", "SYNTHETIC_PRIVATE_TASK", "inline")
    command = ([sys.executable, str(child), "exec", "--json", bundle.render_context()]
               if os.name == "nt" else ["codex", "exec", "--json", bundle.render_context()])
    spec = LaunchSpec(
        executor="codex", command=command, prompt_bundle=bundle,
        injection_metadata=InjectionMetadata("codex", "inline"),
        delivery_mode="inline", dispatch_decision=None, available=True,
        selected_model="synthetic", selected_effort="high",
    )
elif entry_point in ("claude_channel", "claude_agent_view"):
    os.environ["PATH"] = str(work_dir)
    bundle = PromptBundle("workflow", "SYNTHETIC_PRIVATE_TASK", "inline")
    spec = LaunchSpec(
        executor="claude", command=[sys.executable, "-c", "raise AssertionError('must not run')"],
        prompt_bundle=bundle, injection_metadata=InjectionMetadata("claude", "inline"),
        delivery_mode="inline", dispatch_decision=None, available=True,
        selected_model="claude-opus-5", selected_effort="high",
        claude_route=entry_point, claude_sidecar_url="http://127.0.0.1:1",
    )

launcher.sys.platform = "darwin"
observed.clear()
mode[0] = "reject"
try:
    if entry_point == "launch":
        result = launcher.launch(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            lease_authority=UnusedAuthority(),
        )
    else:
        result = launcher.launch_with_spec(
            spec, codex_usage_capture=True, codex_input_capture=True,
            lease_authority=UnusedAuthority(),
        )
finally:
    mode[0] = "off"

print(json.dumps({
    "control_events": control_events,
    "observed": observed,
    "available": result.available,
    "returncode": result.returncode,
    "unavailable_reason": result.unavailable_reason,
    "supervisor_receipt": result.supervisor_receipt,
    "process_pid": result.process_pid,
    "output": result.output,
    "marker_exists": marker.exists(),
}))
"""


@pytest.mark.parametrize("entry_point", ["launch", "launch_with_spec", "claude_channel", "claude_agent_view"])
def test_macos_leased_launch_refusal_starts_no_process_and_opens_no_connection(
    tmp_path, entry_point,
):
    from phase_loop_runtime import launcher

    # Run the audit observer inside a fresh child interpreter so pytest accumulates
    # no permanent sys.addaudithook listeners and no unrelated threads can interfere.
    src_root = str(os.path.dirname(os.path.dirname(launcher.__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = src_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run(
        [
            sys.executable, "-c", _MACOS_LEASE_AUDIT_CHILD,
            json.dumps(sorted(_FORWARD_AUDIT_EVENTS)),
            json.dumps(list(_FORWARD_AUDIT_PREFIXES)),
            entry_point,
            str(tmp_path),
        ],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert completed.returncode == 0, f"audit child failed ({completed.returncode}): {completed.stderr}"
    payload = json.loads(completed.stdout)

    control_events = set(payload["control_events"])
    assert "subprocess.Popen" in control_events, f"process control missed subprocess.Popen: {control_events}"
    assert "socket.__new__" in control_events and "socket.connect" in control_events, (
        f"connection control missed socket events: {control_events}"
    )
    assert control_events & {"_thread.start_new_thread", "_thread.start_joinable_thread"}, (
        f"thread control missed thread start event: {control_events}"
    )

    assert payload["observed"] == [], (
        f"leased macOS refusal ({entry_point}) emitted process/connection/thread audit events: {payload['observed']}"
    )
    assert payload["available"] is False
    assert payload["returncode"] == 1
    assert payload["unavailable_reason"] == "native_macos_leased_execution_requires_linux_worker"
    assert payload["supervisor_receipt"] is None
    assert payload["process_pid"] is None
    assert "Linux worker" in payload["output"]
    assert payload["marker_exists"] is False
