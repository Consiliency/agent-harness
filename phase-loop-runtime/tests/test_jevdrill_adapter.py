import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

from jevdrill_fixture_values import (COUNTER_PLACEHOLDER, JEV_COUNTER_METHOD, JEV_COUNTER_METHOD_SHA256,
                                     load_rows)
from phase_loop_runtime.jevdrill_adapter import JevDrillTransport


FIXTURES = Path(__file__).parent / "fixtures" / "jevdrill"


def fixture(contract):
    return next(row["payload"] for row in load_rows("host.json")
                if row["contract"] == contract and row["accepted"])


def transport(tmp_path, program):
    child = tmp_path / "child.py"
    child.write_text(program)
    return JevDrillTransport((sys.executable, str(child)), tmp_path / "state",
                             FIXTURES, json.loads((FIXTURES / "digests.json").read_text()))


def test_fixture_counter_method_is_the_public_canonical_constant():
    assert hashlib.sha256(JEV_COUNTER_METHOD.encode()).hexdigest() == JEV_COUNTER_METHOD_SHA256
    for name in ("discovery.json", "host.json", "route-inputs.json"):
        raw = (FIXTURES / name).read_text()
        assert JEV_COUNTER_METHOD not in raw and COUNTER_PLACEHOLDER in raw
        loaded = json.dumps(load_rows(name))
        assert COUNTER_PLACEHOLDER not in loaded and JEV_COUNTER_METHOD in loaded


def test_strict_schema_digest_mismatch(tmp_path):
    with pytest.raises(ValueError, match="digest"):
        JevDrillTransport((sys.executable,), tmp_path, FIXTURES, {"NoticeInbox.json": "invalid"})


def test_notice_transport_validates_request_and_response(tmp_path):
    response = fixture("NoticeInbox")
    cli = transport(tmp_path, "import json,sys\njson.load(sys.stdin)\nprint(" + repr(json.dumps(response)) + ")\n")
    assert cli.call("notices", fixture("NoticeRequest")) == response


@pytest.mark.parametrize("output", ["{}", "{} {}", "not json", '{"schema_version":"1","notices":[],"notices":[]}',
                                     '{"schema_version":"1","notices":[],"unexpected":NaN}',
                                     '{"schema_version":"1","notices":[],"unexpected":Infinity}'])
def test_malformed_response_fails_closed(tmp_path, output):
    cli = transport(tmp_path, "import sys\nsys.stdin.read()\nprint(" + repr(output) + ")\n")
    with pytest.raises(Exception):
        cli.call("notices", fixture("NoticeRequest"))


def test_output_is_bounded(tmp_path):
    cli = transport(tmp_path, "import sys\nsys.stdin.read()\nsys.stdout.write('x'*1000001)\nsys.stdout.flush()\n")
    with pytest.raises(ValueError, match="response exceeds"):
        cli.call("notices", fixture("NoticeRequest"))


def test_deadline_includes_prior_work_and_reaps_child(tmp_path):
    cli = transport(tmp_path, "import time\ntime.sleep(60)\n")
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        cli.call("notices", fixture("NoticeRequest"), started_at=started - 4.8)
    assert time.monotonic() - started < 2


def test_expired_budget_never_spawns(tmp_path):
    cli = transport(tmp_path, "raise AssertionError('must not start')\n")
    with pytest.raises(TimeoutError, match="before spawn"):
        cli.call("notices", fixture("NoticeRequest"), started_at=time.monotonic() - 6)


def adapter_fixture(tmp_path, **options):
    from copy import deepcopy
    from phase_loop_runtime.jevdrill_adapter import JevDrillAdapter
    from phase_loop_runtime.models import ModelSelection, PromptBundle

    request = fixture("RouteRequest")
    request["execution_mode"] = "main"
    request["recursion_bypass"] = False
    request["retry_context"] = None
    request["hard_constraints"].update(context_token_limit=32768, total_deadline_ms=5000)
    request["optimization_objective"]["metric_id"] = "raw_token_cost"
    for field in ("harness_id", "execution_target_id"):
        request["envelope"][field] = request["task_id"]
    request["capabilities"].update(verified_at="2026-01-01T00:00:00Z", expires_at="2099-01-01T00:00:00Z",
                                   declared=["text"], runtime=["text"])
    inventory = next(x["payload"] for x in load_rows("route-inputs.json")
                     if x["contract"] == "InventorySnapshot" and x["accepted"])
    candidate = inventory["candidates"][0]
    inventory["target"] = request["envelope"]["execution_target_id"]
    candidate.update(access_route="codex_cli", native_effort={"kind": "explicit", "native_value": "high"},
                     supported_efforts=["high"])
    inputs = {"schema_version": "1", "request": request, "inventory": inventory, "catalog": None,
              "catalog_query": None, "judgment_policy": None, "settings_layers": [], "completion_time_limit_ms": None}
    decision = fixture("RoutingDecision")
    decision["readiness"].update(verified_at="2026-01-01T00:00:00Z", valid_until="2099-01-01T00:00:00Z")
    for field in ("harness_id", "execution_target_id"):
        decision["execution_plan"][field] = request["envelope"][field]
    decision["execution_plan"].update({k: candidate[k] for k in
        ("provider", "model_id", "resolved_model_revision", "access_route", "native_effort")})
    calls, notices = [], []
    cli = transport(tmp_path, "raise AssertionError('test must supply transport call')")
    def call(command, payload, **kwargs):
        calls.append((command, deepcopy(payload)))
        if command == "notices":
            return {"schema_version": "1", "notices": []}
        if command == "report":
            return {"status": "accepted", "event_id": payload["event"]["event_id"], "durable": True}
        return deepcopy(decision)
    cli.call = call
    adapter = JevDrillAdapter(cli, tmp_path / "queue" / "reports.sqlite", inputs_for=lambda _: deepcopy(inputs),
                              verify_candidate=options.get("verify_candidate", lambda *_: True),
                              limits_enforced=options.get("limits_enforced", lambda *_: True),
                              capabilities_for=options.get("capabilities_for", lambda _: (["text"], ["text"])),
                              notice_sink=notices.append)
    kwargs = {"executor": "codex", "model_selection": ModelSelection("execute", "original", "high"),
              "prompt_bundle": PromptBundle("workflow", "required", "inline")}
    return adapter, inputs, decision, kwargs, calls, notices


def test_adapter_preserves_host_authority_and_reports_without_output(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path)
    original = kwargs["prompt_bundle"]
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert prepared["model_selection"].model == "model-a"
    assert prepared["json_output"] is True
    assert original.body == prepared["prompt_bundle"].body == "required"
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    result = LaunchResult(command=["synthetic"], returncode=0, output="PRIVATE_OUTPUT_SENTINEL")
    observed = adapter.launch(lambda *_args, **_kwargs: result, spec)
    assert observed.output == result.output
    assert observed.jevdrill_execution_run["selected_plan_id"] == observed.jevdrill_execution_run["applied_plan_id"]
    adapter.flush()
    adapter.flush()
    reports = [value for command, value in calls if command == "report"]
    assert [r["event"]["payload"].get("event_type") for r in reports] == ["started", "completed", None]
    measurements = reports[-1]["event"]["payload"]["measurements"]
    assert measurements[0]["measurement_value"]["value"] >= 0
    assert all(m["measurement_value"] == {"kind": "unknown", "reason": "not_reported"} for m in measurements[1:])
    assert all(b"PRIVATE_OUTPUT_SENTINEL" not in p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    assert not adapter._pending


@pytest.mark.parametrize("outcome", ["completed", "failed", "exception", "report_failure"])
def test_timings_separate_routing_launch_and_reporting(tmp_path, monkeypatch, outcome):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    clock = [0]
    monkeypatch.setattr(time, "monotonic_ns", lambda: clock[0])
    def advance(ms):
        clock[0] += ms * 1_000_000
    inputs_for = adapter.inputs_for
    def inputs(context):
        advance(22)
        return inputs_for(context)
    adapter.inputs_for = inputs
    report = adapter._report
    def delayed_report(binding, event_type=None, **kwargs):
        advance(7)
        if outcome == "report_failure" and event_type == "completed":
            raise OSError("PRIVATE_REPORT_FAILURE")
        return report(binding, event_type, **kwargs)
    adapter._report = delayed_report
    flush = adapter.flush
    def delayed_flush():
        advance(11)
        return flush()
    adapter.flush = delayed_flush
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    advance(500)  # Caller work between preparation and launch is outside the receipt.
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"],
                           selected_model="model-a", effective_effort="high", claude_route=None)
    def execute(*_args, **_kwargs):
        advance(55)
        if outcome == "exception":
            raise RuntimeError("PRIVATE_EXECUTOR_FAILURE")
        return LaunchResult(command=["synthetic"], returncode=1 if outcome == "failed" else 0)
    if outcome == "exception":
        with pytest.raises(RuntimeError, match="PRIVATE_EXECUTOR_FAILURE"):
            adapter.launch(execute, spec)
    else:
        result = adapter.launch(execute, spec)
        assert result.jevdrill_timings == {
            "schema_version": "1", "method": "monotonic_ns", "unit": "ms",
            "routing_ms": 22, "launcher_ms": 55,
            "reporting_ms": 14 if outcome == "report_failure" else 32,
            "provider_generation_ms": None}
        assert result.event_metadata()["jevdrill_timings"] == result.jevdrill_timings
        assert result.returncode == (1 if outcome == "failed" else 0)
        assert "PRIVATE" not in json.dumps(result.event_metadata())
    if outcome == "report_failure":
        assert adapter.delivery_warnings[-1]["status"] == "delivery_failed"
    else:
        adapter.flush()
        adapter.flush()
        reports = [value for command, value in calls if command == "report"]
        assert reports[1]["event"]["payload"]["event_type"] == (
            "failed" if outcome in ("failed", "exception") else "completed")
        assert reports[-1]["event"]["payload"]["measurements"][0]["measurement_value"]["value"] == 55
        assert all("jevdrill_timings" not in json.dumps(report) for report in reports)


def test_unbound_launch_has_no_timing_receipt(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    result = LaunchResult(command=["synthetic"], returncode=0)
    assert adapter.launch(lambda *_args, **_kwargs: result,
                          SimpleNamespace(prompt_bundle=kwargs["prompt_bundle"])) is result
    assert result.jevdrill_timings is None
    assert "jevdrill_timings" not in result.event_metadata()


@pytest.mark.parametrize("outcome", ["needs_context", "no_compatible_plan", "constraint_conflict", "routing_failed"])
def test_nonready_never_constructs_launch(tmp_path, outcome):
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path)
    decision["status"] = outcome
    with pytest.raises(JevDrillUnavailable, match=outcome) as rejected:
        adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert rejected.value.decision == decision


def test_forged_capability_or_candidate_cannot_expand_authority(tmp_path):
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path, capabilities_for=lambda _: ([], []))
    with pytest.raises(JevDrillUnavailable, match="unverified"):
        adapter.prepare(mode="main", dry_run=False, **kwargs)
    routed = next(value for command, value in calls if command == "route")
    assert routed["inventory"]["candidates"] == []
    assert routed["request"]["capabilities"]["runtime"] == []


def test_override_staleness_and_final_token_enforcement(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path, limits_enforced=lambda *_: False)
    limits = {"input_tokens": 10000, "output_tokens": 2000}
    inputs["request"]["hard_constraints"]["execution_token_limits"] = limits
    inputs["inventory"]["candidates"][0]["execution_token_limits"] = limits
    overridden = {**kwargs, "model_selection": replace(kwargs["model_selection"], source="user_override")}
    with pytest.raises(JevDrillUnavailable, match="override"):
        adapter.prepare(mode="main", dry_run=False, **overridden)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    with pytest.raises(JevDrillUnavailable, match="bounds"):
        adapter.launch(lambda *_: pytest.fail("must not launch"), spec)
    inputs["inventory"]["expires_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(JevDrillUnavailable, match="stale"):
        adapter.prepare(mode="main", dry_run=False, **kwargs)


def test_readiness_expiring_after_prepare_is_rejected_at_the_final_recheck(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from phase_loop_runtime import jevdrill_adapter
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path)
    now = datetime.now(timezone.utc)
    # Fresh at prepare; every other freshness row stays valid until 2099.
    decision["readiness"]["valid_until"] = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(hours=2)

    monkeypatch.setattr(jevdrill_adapter, "datetime", Later)
    launched = []
    with pytest.raises(JevDrillUnavailable, match="not enforceable"):
        adapter.launch(lambda *args, **_kwargs: launched.append(args), spec)
    assert launched == []
    assert [command for command, _ in calls if command == "report"] == []
    assert adapter.queue.status()["records"] == 0


def test_dry_run_and_recursion_bypass_do_not_route(tmp_path):
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path)
    assert adapter.prepare(mode="main", dry_run=True, **kwargs) == kwargs
    inputs["request"]["recursion_bypass"] = True
    assert adapter.prepare(mode="main", dry_run=False, **kwargs) == kwargs
    assert calls == []


def test_no_requested_ceiling_does_not_require_token_enforcement(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(
        tmp_path, limits_enforced=lambda *_: pytest.fail("No ceiling requires enforcement"))
    inputs["request"]["hard_constraints"]["spending_ceiling"] = None
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    launched = []
    def execute(*args, **kwargs):
        launched.append(True)
        return LaunchResult(command=["synthetic"], returncode=0)
    result = adapter.launch(execute, spec)
    assert launched == [True]
    assert result.returncode == 0


@pytest.mark.parametrize("ceiling", ["spending", "tokens", "retry_spend"])
def test_requested_ceiling_rejects_unproven_executor_limits(tmp_path, ceiling):
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, inputs, decision, kwargs, calls, notices = adapter_fixture(tmp_path)
    if ceiling == "spending":
        inputs["request"]["hard_constraints"]["spending_ceiling"] = {"amount": "100", "currency": "USD"}
    elif ceiling == "tokens":
        inputs["request"]["hard_constraints"]["execution_token_limits"] = {"input_tokens": 10000, "output_tokens": 2000}
    else:
        inputs["request"]["retry_context"] = fixture("RouteRequest")["retry_context"]
        inputs["request"]["retry_context"]["remaining_spend"] = {"amount": "100", "currency": "USD"}
    with pytest.raises(JevDrillUnavailable, match="unverified"):
        adapter.prepare(mode="main", dry_run=False, **kwargs)
    routed = next(value for command, value in calls if command == "route")
    assert routed["inventory"]["candidates"] == []


def test_production_sanitizer_rejects_raw_fields_and_erases_free_text(tmp_path):
    adapter, *_ = adapter_fixture(tmp_path)
    report = fixture("ReportRequest")
    for field in ("harness_id", "execution_target_id"):
        report["envelope"][field] = report["event"]["task_id"]
    sentinel = "PRIVATE_REASON_AND_PATH_SENTINEL"
    report["event"]["payload"]["reason"] = sentinel
    report["envelope"]["extensions"] = {"host.secret": sentinel}
    report["event"]["source_id"] = sentinel
    assert adapter.queue.enqueue(report) == "queued"
    assert sentinel.encode() not in adapter.queue.path.read_bytes()
    report["raw_output"] = sentinel
    with pytest.raises(Exception):
        adapter.queue.enqueue(report)


@pytest.mark.parametrize("entrypoint", ["main", "delegated", "lane"])
def test_real_runner_construction_sites_reach_bridge(tmp_path, monkeypatch, entrypoint):
    from phase_loop_runtime import runner
    from phase_loop_runtime.models import PromptBundle, DelegationRequest, DelegationBudget, HarnessLaneAssignment
    from phase_loop_test_utils import make_repo, write_phase_plan

    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "RUNNER", roadmap, owned_files=("notes.md",))
    monkeypatch.setattr(runner, "build_prompt", lambda *_args, **_kwargs:
                        PromptBundle("synthetic-workflow", "synthetic-required-guidance", "inline"))
    entered, launched = [], []
    class Witness:
        def prepare(self, *, mode, dry_run, **kwargs):
            entered.append((mode, dry_run, kwargs))
            return kwargs
        def launch(self, launch, spec, **kwargs):
            launched.append(spec)
            return launch(spec, **kwargs)
    adapter = Witness()
    if entrypoint == "main":
        runner.run_loop(repo, roadmap, phase="RUNNER", dry_run=True, jevdrill_adapter=adapter)
    elif entrypoint == "delegated":
        runner.launch_delegated_child(repo=repo, roadmap=roadmap, parent_phase="RUNNER", parent_action="execute",
            plan=plan, request=DelegationRequest(request_id="synthetic", product_action="review", target_executor="codex",
            reason="synthetic conformance", owned_files=("notes.md",), expected_output="findings",
            budget=DelegationBudget(max_seconds=60)), dry_run=True, jevdrill_adapter=adapter)
    else:
        runner.launch_harness_lane_work_unit(repo=repo, roadmap=roadmap, plan=plan,
            assignment=HarnessLaneAssignment(phase="RUNNER", lane_id="SL-0", work_unit_kind="lane_execute",
                                             owned_files=("notes.md",)), dry_run=True, jevdrill_adapter=adapter)
    assert len(entered) == len(launched) == 1
    assert entered[0][0] == entrypoint
    assert entered[0][2]["repo"] == repo
    assert launched[0].prompt_bundle.body == "synthetic-required-guidance"


@pytest.mark.jevdrill_installed
def test_real_jevdrill_cli_route_and_durable_reports(tmp_path):
    from types import SimpleNamespace
    from jevdrill_install import resolve_install
    from phase_loop_runtime.launcher import LaunchResult
    # JEVHOST §6 [C1]: no skip of its own; conftest skips only when neither variable is set.
    argv = resolve_install().cli_argv
    adapter, inputs, _, kwargs, _, _ = adapter_fixture(tmp_path)
    adapter.transport = JevDrillTransport(argv, tmp_path / "jev-state", FIXTURES,
        json.loads((FIXTURES / "digests.json").read_text()))
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    adapter.launch(lambda *_args, **_kwargs: LaunchResult(command=["synthetic"], returncode=0, output=""), spec)
    assert adapter.flush() == "accepted"
    assert adapter.flush() == "accepted"
    assert adapter.queue.status()["records"] == 0
    envelope = inputs["request"]["envelope"]
    scope = {"project_id": envelope["project_id"], "workspace_id": envelope["workspace_id"],
             "producer": envelope["harness_id"], "operation": "route"}
    assert adapter.delete_task(scope, inputs["request"]["task_id"])["status"] == "deleted"
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    with pytest.raises(JevDrillUnavailable, match="deleted"):
        adapter.prepare(mode="main", dry_run=False, **kwargs)


def test_conflict_exit_is_a_valid_terminal_acknowledgment(tmp_path):
    response = next(row["payload"] for row in load_rows("host.json")
                    if row["contract"] == "ReportAcknowledgment" and row["accepted"]
                    and row["payload"]["status"] == "conflict")
    cli = transport(tmp_path, "import json,sys\njson.load(sys.stdin)\nprint(" + repr(json.dumps(response)) + ")\nsys.exit(3)\n")
    assert cli.call("report", fixture("ReportRequest")) == response


def test_route_and_notice_share_deadline(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    original = adapter.transport.call
    starts = []
    def call(command, payload, **options):
        starts.append(options["started_at"])
        return original(command, payload, **options)
    adapter.transport.call = call
    adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert len(starts) == 2 and starts[0] == starts[1]


def test_abandoned_prompt_binding_is_collected(tmp_path):
    import gc
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert adapter._pending
    del prepared
    gc.collect()
    assert not adapter._pending


def test_delivery_failure_does_not_replace_executor_result(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    monkeypatch.setattr(adapter, "flush", lambda: (_ for _ in ()).throw(OSError("synthetic outage")))
    result = LaunchResult(command=["synthetic"], returncode=0, output="")
    assert adapter.launch(lambda *_args, **_kwargs: result, spec).output == result.output
    assert adapter.queue.status()["records"] == 3
    assert adapter.delivery_warnings[-1]["status"] == "delivery_failed"


@pytest.mark.parametrize("entrypoint", ["main", "delegated", "lane"])
@pytest.mark.parametrize("ready", [True, False])
def test_live_runner_routes_before_controlled_executor(tmp_path, monkeypatch, entrypoint, ready):
    from copy import deepcopy
    from phase_loop_runtime import runner
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    from phase_loop_runtime.models import PromptBundle, DelegationRequest, DelegationBudget, HarnessLaneAssignment
    from phase_loop_test_utils import make_repo, write_phase_plan
    adapter, inputs, decision, _, calls, _ = adapter_fixture(tmp_path)
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "RUNNER", roadmap, owned_files=("notes.md",))
    monkeypatch.setattr(runner, "build_prompt", lambda *_args, **_kwargs:
                        PromptBundle("synthetic-workflow", "required", "inline"))
    monkeypatch.setattr(runner, "run_auth_preflight", lambda _: None)
    entered, launched = [], []
    def inputs_for(context):
        entered.append(context)
        inputs["request"]["execution_mode"] = "main" if entrypoint == "main" else "delegated"
        selection = context["model_selection"]
        candidate = inputs["inventory"]["candidates"][0]
        candidate.update(model_id=selection.model, native_effort={"kind": "explicit", "native_value": selection.effort},
                         supported_efforts=[selection.effort])
        decision["execution_plan"].update(model_id=selection.model, native_effort=candidate["native_effort"])
        return deepcopy(inputs)
    adapter.inputs_for = inputs_for
    if not ready:
        decision["status"] = "no_compatible_plan"
    class ReachedExecutor(Exception):
        pass
    def controlled_executor(spec, **kwargs):
        launched.append(spec)
        raise ReachedExecutor()
    monkeypatch.setattr(runner, "launch_with_spec", controlled_executor)
    with pytest.raises(ReachedExecutor if ready else JevDrillUnavailable):
        if entrypoint == "main":
            runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex", model="gpt-5.4",
                            effort="high", jevdrill_adapter=adapter)
        elif entrypoint == "delegated":
            runner.launch_delegated_child(repo=repo, roadmap=roadmap, parent_phase="RUNNER", parent_action="execute",
                plan=plan, request=DelegationRequest(request_id="synthetic", product_action="review", target_executor="codex",
                reason="synthetic conformance", owned_files=("notes.md",), expected_output="findings",
                budget=DelegationBudget(max_seconds=60)), jevdrill_adapter=adapter)
        else:
            runner.launch_harness_lane_work_unit(repo=repo, roadmap=roadmap, plan=plan,
                assignment=HarnessLaneAssignment(phase="RUNNER", lane_id="SL-0", work_unit_kind="lane_execute",
                    owned_files=("notes.md",)), dry_run=False, jevdrill_adapter=adapter)
    assert len(entered) == 1
    assert entered[0]["mode"] == entrypoint
    assert len(launched) == int(ready)
    assert any(command == "route" for command, _ in calls)
    if ready:
        original_source = entered[0]["model_selection"].source
        assert launched[0].profile_source == ("jevdrill" if original_source in ("default", "codex_default") else original_source)
        assert launched[0].prompt_bundle.body == "required"


def test_declarations_intersect_runtime_and_reject_ignored_or_ambiguous_input(tmp_path):
    from phase_loop_runtime.jevdrill_adapter import load_harness_declarations, JevDrillUnavailable
    from phase_loop_test_utils import make_repo
    repo = make_repo(tmp_path)
    path = repo / ".jevdrill" / "harnesses.yaml"
    path.parent.mkdir()
    adapter, inputs, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    envelope = inputs["request"]["envelope"]
    declaration = {"schema_version": "1", "harnesses": [{"harness_id": envelope["harness_id"],
        "execution_target_id": envelope["execution_target_id"], "declared_capabilities": [], "access_routes": ["codex_cli"]}]}
    path.write_text(json.dumps(declaration))
    assert load_harness_declarations(repo) == declaration
    with pytest.raises(JevDrillUnavailable, match="unverified"):
        adapter.prepare(mode="main", dry_run=False, **kwargs, repo=repo)
    assert next(value for command, value in calls if command == "route")["inventory"]["candidates"] == []
    (repo / ".gitignore").write_text(".jevdrill/\n")
    with pytest.raises(ValueError, match="read allowance"):
        load_harness_declarations(repo)
    assert load_harness_declarations(repo, allowed_ignored_paths=(path,)) == declaration
    path.write_text('schema_version: "1"\nschema_version: "1"\nharnesses: []\n')
    with pytest.raises(ValueError, match="Duplicate"):
        load_harness_declarations(repo, allowed_ignored_paths=(path,))
    path.write_text('schema_version: "1"\nharnesses: &a []\nextra: *a\n')
    with pytest.raises(ValueError, match="aliases"):
        load_harness_declarations(repo, allowed_ignored_paths=(path,))


def test_unregistered_measurements_and_evaluation_text_never_persist(tmp_path):
    adapter, *_ = adapter_fixture(tmp_path)
    report = fixture("ReportRequest")
    for field in ("harness_id", "execution_target_id"):
        report["envelope"][field] = report["event"]["task_id"]
    sentinel = "PRIVATE_EVALUATION_PATH"
    report["event"]["payload"] = {"kind": "evaluation", "check_results": {sentinel: True},
        "evaluator_ref": sentinel, "rubric_revision": sentinel, "measurements": []}
    assert adapter.queue.enqueue(report) == "queued"
    assert sentinel.encode() not in adapter.queue.path.read_bytes()
    report["event"]["payload"]["measurements"] = [{"metric_id": sentinel, "metric_version": "1", "scope": "run",
        "source": "evaluator", "method": "evaluator", "counting_semantics": "not_applicable", "parent_metric_id": None,
        "measurement_value": {"kind": "known", "unit": "score", "value": 1}}]
    with pytest.raises(ValueError, match="Unregistered"):
        adapter.queue.enqueue(report)


def test_broken_notice_sink_does_not_mask_routing_outcome(tmp_path):
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, _, decision, kwargs, _, _ = adapter_fixture(tmp_path)
    original = adapter.transport.call
    def call(command, payload, **options):
        if command == "notices":
            return fixture("NoticeInbox")
        return original(command, payload, **options)
    adapter.transport.call = call
    adapter.notice_sink = lambda _: (_ for _ in ()).throw(RuntimeError("synthetic sink error"))
    decision["status"] = "no_compatible_plan"
    with pytest.raises(JevDrillUnavailable) as error:
        adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert error.value.decision == decision


def test_guidance_is_verified_injected_once_and_deactivated(tmp_path):
    import hashlib
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    from phase_loop_runtime.jevdrill_adapter import JevDrillUnavailable
    adapter, inputs, decision, kwargs, calls, _ = adapter_fixture(tmp_path)
    text = "SYNTHETIC_OPTIONAL_GUIDANCE"
    digest = hashlib.sha256(text.encode()).hexdigest()
    guidance = {"admission": "explicitly_enabled", "authority": "project", "resource_id": "fixture",
                "revision": "1", "content_hash": digest, "role": "optional", "token_count": None,
                "task_id": inputs["request"]["task_id"]}
    decision["execution_plan"].update(optional_guidance=[guidance, guidance], guidance_action="inject")
    inputs["catalog"] = {"schema_version": "1", "revision": "fixture", "resources": [{
        "resource_id": "fixture", "revision": "1", "content_hash": digest, "instructions": text,
        "admission": "explicitly_enabled", "domain": "fixture", "specialty": "fixture", "task_family": "fixture",
        "facets": [], "aliases": [], "source_occurrences": [], "conflicts": [], "rights": "synthetic",
        "benchmark_effort": None, "benchmark_protocol": None, "benchmark_split": None}]}
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    assert prepared["prompt_bundle"].body.count(text) == 1
    assert kwargs["prompt_bundle"].body == "required"
    retried = adapter.prepare(mode="main", dry_run=False, **{**kwargs, "prompt_bundle": prepared["prompt_bundle"]})
    assert retried["prompt_bundle"].body.count(text) == 1
    decision["execution_plan"].update(optional_guidance=[], guidance_action="none")
    unrelated = adapter.prepare(mode="main", dry_run=False, **{**kwargs, "prompt_bundle": retried["prompt_bundle"]})
    assert unrelated["prompt_bundle"].body == "required"
    decision["execution_plan"].update(optional_guidance=[guidance], guidance_action="inject")
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    adapter.launch(lambda *_a, **_k: LaunchResult(command=["synthetic"], returncode=0), spec)
    while adapter.flush() != "empty":
        pass
    assert any(value["event"]["payload"].get("event_type") == "guidance_deactivated"
               for command, value in calls if command == "report")
    inputs["catalog"]["resources"][0]["instructions"] += " changed"
    with pytest.raises(JevDrillUnavailable, match="guidance"):
        adapter.prepare(mode="main", dry_run=False, **kwargs)


def test_observed_substitution_is_not_attributed_to_selected_plan(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    result = adapter.launch(lambda *_a, **_k: LaunchResult(command=["synthetic"], returncode=0, selected_model="other"), spec)
    assert result.jevdrill_execution_run["applied_plan_id"] is None
    assert result.jevdrill_execution_run["substitution_reason"] == "executor_identity_mismatch"
    assert result.event_metadata()["jevdrill_execution_run"] == result.jevdrill_execution_run


def test_valid_oversized_input_is_rejected_before_spawn(tmp_path):
    _, inputs, *_ = adapter_fixture(tmp_path)
    inputs["request"]["task_representation"] = "x" * 1_000_001
    cli = transport(tmp_path, "raise AssertionError('must not spawn')")
    with pytest.raises(ValueError, match="request exceeds"):
        cli.call("route", inputs)


def test_unavailable_executor_is_not_reported_as_completed(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime.launcher import LaunchResult
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a",
                           effective_effort="high", claude_route=None)
    result = adapter.launch(lambda *_a, **_k: LaunchResult(
        command=["synthetic"], returncode=None, available=False,
        unavailable_reason="native_macos_leased_execution_requires_linux_worker"), spec)
    for _ in range(3):
        adapter.flush()
    assert result.jevdrill_execution_run["applied_plan_id"] is None
    assert result.jevdrill_execution_run["substitution_reason"] == "executor_unavailable"
    events = [payload["event"]["payload"].get("event_type") for command, payload in calls if command == "report"]
    assert "failed" in events and "completed" not in events


def test_macos_lease_rejection_precedes_authority_transfer(monkeypatch, tmp_path):
    from phase_loop_runtime import launcher
    class UnusedAuthority:
        def fileno(self):
            raise AssertionError("lease must not be transferred")
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    marker = tmp_path / "must-not-start"
    result = launcher.launch([sys.executable, "-c", "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"],
                             lease_authority=UnusedAuthority())
    assert result.available is False
    assert result.unavailable_reason == "native_macos_leased_execution_requires_linux_worker"
    assert "Linux worker" in result.output
    assert result.supervisor_receipt is None
    assert not marker.exists()
