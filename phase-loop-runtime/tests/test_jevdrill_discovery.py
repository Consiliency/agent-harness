"""Installed discovery, harness-owned plan lanes and linked executor construction."""
import json
import os
import sqlite3
import sys
import threading
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from phase_loop_runtime import runner
from phase_loop_runtime.jevdrill_adapter import JevDrillTransport, JevDrillUnavailable
from phase_loop_runtime.launcher import build_launch_request, build_launch_spec, launch, launch_with_spec
from phase_loop_runtime.models import ModelSelection, PromptBundle
from phase_loop_test_utils import make_repo, write_phase_plan
from jevdrill_fixture_values import load_rows
from test_jevdrill_adapter import FIXTURES, adapter_fixture


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)
    elif isinstance(value, str):
        for index, char in enumerate(value):
            if char == "{":
                try:
                    child, _ = json.JSONDecoder().raw_decode(value[index:])
                    if isinstance(child, dict):
                        yield child
                except ValueError:
                    pass


@pytest.fixture
def installed_discovery(tmp_path, monkeypatch):
    python = os.environ.get("JEVDRILL_TEST_PYTHON")
    if not python:
        cli = os.environ.get("JEVDRILL_TEST_CLI")
        assert cli, "Installed JEV CLI is required; discovery cannot be skipped"
        python = str(Path(cli).parent / ("python.exe" if os.name == "nt" else "python"))
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            rows = list(objects(body))
            option = next(row for row in rows if "option_id" in row and "level" in row)
            objective = next(row["objective"] for row in rows if "objective" in row)
            answer = option["level"] == "resource" and (
                ("alpha" in objective and "alpha" in (option.get("description") or "")) or
                ("beta" in objective and "beta" in (option.get("description") or "")))
            requests.append({"option_id": option["option_id"], "level": option["level"],
                             "answer": answer})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"model": "jev-latest", "answers": {
                "result": {"type": "noul", "noul": 1 if answer else 0}},
                "usage": {"input_tokens": 123}}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("JEVDRILL_TEST_URL", f"http://127.0.0.1:{server.server_port}")
    trace = tmp_path / "entered.jsonl"
    wrapper = tmp_path / "installed_observer.py"
    wrapper.write_text(
        "from jevdrill import cli\n"
        "import sys,json\n"
        "import jevdrill.integrations.jev as bridge\n"
        "import baml_sdk\n"
        "bridge.ObserveDiscoveryOption=baml_sdk.MockObserveDiscoveryOption\n"
        "def profile(frame,event,result):\n"
        "    name=frame.f_code.co_name\n"
        "    if event=='call' and name in ('main','open_application','discover','next_question','route') "
        "and ('jevdrill' in frame.f_code.co_filename):\n"
        f"        with open({str(trace)!r},'a') as stream: stream.write(json.dumps({{'entered':name}})+'\\n')\n"
        "sys.setprofile(profile)\n"
        "raise SystemExit(cli.main())\n"
    )
    adapter, base, _, kwargs, _, _ = adapter_fixture(tmp_path)
    adapter.transport = JevDrillTransport((python, str(wrapper)), tmp_path / "jev.sqlite",
        FIXTURES, json.loads((FIXTURES / "digests.json").read_text()))
    inputs = deepcopy(next(row["payload"] for row in load_rows("discovery.json")
                           if row["accepted"] and row["contract"] == "DiscoveryInputs"))
    inputs["envelope"].update({key: base["request"]["envelope"][key] for key in (
        "project_id", "workspace_id", "harness_id", "execution_target_id")})
    inputs["work_objective_text"] = "Build with alpha guidance"
    yield adapter, inputs, base, kwargs, requests, trace
    server.shutdown()
    server.server_close()
    thread.join()


def linked_task(base, inputs, task, index):
    value = deepcopy(base)
    request = value["request"]
    request["task_id"] = task["task_id"]
    request["envelope"].update(request_id=str(uuid4()), idempotency_key=task["task_id"])
    request["hard_constraints"] = deepcopy(inputs["hard_constraints"])
    request["optimization_objective"]["acceptance_requirements"] = inputs["acceptance_requirements"]
    value["catalog"] = deepcopy(inputs["catalog"])
    candidate = value["inventory"]["candidates"][0]
    candidate.update(model_id="model-0", resolved_model_revision="model-0-v1",
                     native_effort={"kind": "explicit", "native_value": "high"},
                     supported_efforts=["high"], completion_time_ms=1000)
    candidate["guidance_options"] = [
        {**{key: row[key] for key in ("resource_id", "revision", "content_hash")},
         "role": "optional-" + str(number), "authority": "synthetic-admission",
         "admission": row["admission"], "task_id": task["task_id"], "token_count": None}
        for number, row in enumerate(inputs["catalog"]["resources"])]
    second = deepcopy(candidate)
    second.update(candidate_id="fast", model_id="model-1", resolved_model_revision="model-1-v1",
                  native_effort={"kind": "explicit", "native_value": "low"},
                  supported_efforts=["low"], completion_time_ms=10)
    second["rates"].update(input_rate="0.01", output_rate="0.01")
    value["inventory"]["candidates"].append(second)
    if index:
        value["completion_time_limit_ms"] = 20
    return {"schema_version": "2", "route_inputs": value, "discovery_ref": task["discovery_ref"]}


def host_plan(tmp_path, result, events):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs/phase-plans-v1.md"
    # Synthetic planner output follows the same public lane contract as an ordinary plan.
    body = "# RUNNER\n\n## Lanes\n\n"
    for index in range(2):
        body += f"### SL-{index} - Task {index}\n- **Owned files**: `task-{index}.py`\n"
    prompt = PromptBundle("synthetic-planner", "Plan two tasks\n" + "\n".join(
        result["details"]["assembled_instructions"]), "inline")
    request = build_launch_request(executor="codex", action="plan", repo=repo,
        roadmap=roadmap, phase="RUNNER", plan=None, model_selection=ModelSelection(
            "plan", "model-planner", "high"), prompt_bundle=prompt,
        json_output=False, bypass_approvals=False)
    spec = build_launch_spec(request)
    events.extend(["planning.build_launch_request", "planning.build_launch_spec"])
    assert all(text in spec.prompt_bundle.body for text in result["details"]["assembled_instructions"])
    outcome = launch_with_spec(replace(spec, executor="command", command=[sys.executable, "-I", "-S", "-c",
                              "print(" + repr(body) + ")"], available=True))
    events.append("planning.executor")
    assert outcome.returncode == 0 and spec.prompt_bundle is prompt
    plan = write_phase_plan(repo, "RUNNER", roadmap, body=outcome.output)
    return plan


@pytest.mark.parametrize("objective", ["alpha", "beta"])
def test_installed_discovery_decomposition_two_task_launch(installed_discovery, tmp_path, objective):
    adapter, inputs, base, kwargs, observations, trace = installed_discovery
    inputs["work_objective_text"] = f"Build with {objective} guidance"
    events = []
    result, tasks = runner.discover_jevdrill_work_units(adapter, inputs,
        plan_objective=lambda value: host_plan(tmp_path, value, events))
    assert result["status"] == "selected_guidance"
    assert [g["resource_id"] for g in result["details"]["guidance_refs"]] == [objective]
    assert len(tasks) == 2 and tasks[0]["task_id"] != tasks[1]["task_id"]
    parent = kwargs["prompt_bundle"]
    runs = []
    for index, task in enumerate(tasks):
        wrapper = linked_task(base, inputs, task, index)
        adapter.inputs_for = lambda _context, value=wrapper: deepcopy(value)
        prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
        events.append(f"task.{task['assignment'].lane_id}.route-v2")
        json_output = prepared.pop("json_output", False)
        spec = build_launch_spec(build_launch_request(**prepared, action="execute",
            repo=tmp_path, roadmap=tmp_path / "roadmap.md", phase=None, plan=None,
            json_output=json_output, bypass_approvals=False))
        events.extend(["task.build_launch_request", "task.build_launch_spec"])
        assert parent.body == "required"
        assert all("Synthetic " + other + " instructions" not in spec.prompt_bundle.body
                   for other in ("alpha", "beta") if other != objective)
        outcome = adapter.launch(lambda _spec, **_kw: launch([sys.executable, "-I", "-S",
            "-c", "print('{}')"]), spec)
        events.append("task.executor")
        assert outcome.returncode == 0
        for _ in range(4):
            adapter.flush()
        runs.append({"task_id": task["task_id"], "discovery_ref": task["discovery_ref"],
                     "decision_id": adapter.last_decision["details"]["routing_decision_id"],
                     "execution_run": outcome.jevdrill_execution_run,
                     "model": spec.selected_model, "effort": spec.effective_effort,
                     "timings": outcome.jevdrill_timings})
    assert runs[0]["model"] != runs[1]["model"] and runs[0]["effort"] != runs[1]["effort"]
    entered = [json.loads(line)["entered"] for line in trace.read_text().splitlines()]
    assert {"main", "open_application", "discover", "next_question", "route"} <= set(entered)
    assert any(not row["answer"] and row["level"] != "resource" for row in observations)
    with sqlite3.connect(adapter.queue.path) as db:
        assert db.execute("SELECT COUNT(*) FROM task_bindings").fetchone()[0] == len(runs)
    if output := os.environ.get("JEVDRILL_TEST_ARTIFACTS"):
        Path(output, f"discovery-{objective}.json").write_text(json.dumps({"flow": "discovery",
            "objective": objective, "entered": entered, "construction_events": events,
            "observations": observations, "runs": runs}))


@pytest.mark.parametrize("fault", ["forged", "deleted", "stale_catalog", "relaxed", "decline"])
def test_entered_linked_launch_rejections(installed_discovery, tmp_path, fault):
    adapter, inputs, base, kwargs, _, trace = installed_discovery
    result, tasks = runner.discover_jevdrill_work_units(adapter, inputs,
        plan_objective=lambda value: host_plan(tmp_path, value, []))
    wrapper = linked_task(base, inputs, tasks[0], 0)
    adapter.inputs_for = lambda _context: deepcopy(wrapper)
    if fault == "forged":
        wrapper["discovery_ref"]["trace_digest"] = "0" * 64
    elif fault == "relaxed":
        wrapper["route_inputs"]["request"]["hard_constraints"]["max_attempts"] += 1
    elif fault == "decline":
        adapter.recommendation_action = lambda *_: "decline"
    if fault in ("forged", "relaxed", "decline"):
        with pytest.raises((JevDrillUnavailable, OSError)):
            adapter.prepare(mode="main", dry_run=False, **kwargs)
    else:
        prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
        json_output = prepared.pop("json_output", False)
        spec = build_launch_spec(build_launch_request(**prepared, action="execute", repo=tmp_path,
            roadmap=tmp_path / "roadmap.md", phase=None, plan=None,
            json_output=json_output, bypass_approvals=False))
        if fault == "deleted":
            envelope = inputs["envelope"]
            scope = {"project_id": envelope["project_id"], "workspace_id": envelope["workspace_id"],
                     "producer": "different-producer", "operation": "discover"}
            actual = adapter.transport.call
            def lose_delete(command, value, **kw):
                response = actual(command, value, **kw)
                if command == "delete-discovery":
                    raise OSError("Synthetic lost deletion acknowledgment")
                return response
            adapter.transport.call = lose_delete
            with pytest.raises(OSError):
                adapter.delete_objective(scope, inputs["work_objective_id"])
            assert adapter.queue.objective_deleted(inputs["envelope"], inputs["work_objective_id"])
        else:
            wrapper["route_inputs"]["catalog"]["revision"] = "changed"
        with pytest.raises(JevDrillUnavailable):
            adapter.launch(lambda *_a, **_kw: pytest.fail("Rejected objective launched"), spec)
    assert "discover" in [json.loads(line)["entered"] for line in trace.read_text().splitlines()]
    if output := os.environ.get("JEVDRILL_TEST_ARTIFACTS"):
        Path(output, f"discovery-control-{fault}.json").write_text(json.dumps({
            "flow": "discovery-control", "fault": fault,
            "discovery_id": result["details"]["discovery_id"],
            "task_id": tasks[0]["task_id"], "rejected_before_execution": True}))


def test_entered_discovery_requires_harness_decomposition(installed_discovery, tmp_path):
    adapter, inputs, _, _, _, trace = installed_discovery
    def bypass(_result):
        plan = tmp_path / "bypassed.md"
        plan.write_text("# An objective is not a task plan\n")
        return plan
    with pytest.raises(JevDrillUnavailable, match="task lanes"):
        runner.discover_jevdrill_work_units(adapter, inputs, plan_objective=bypass)
    assert "discover" in trace.read_text()


@pytest.mark.parametrize("status", ["no_optional_guidance", "needs_context", "constraint_conflict", "discovery_failed"])
def test_installed_discovery_status_gates_planning(installed_discovery, tmp_path, status):
    adapter, inputs, _, _, observations, trace = installed_discovery
    planned = []
    if status == "no_optional_guidance":
        inputs["catalog"]["resources"] = []
        inputs["descriptions"] = []
    elif status == "needs_context":
        inputs["work_objective_text"] = ""
    elif status == "constraint_conflict":
        inputs["required_guidance"] = [{**{key: inputs["catalog"]["resources"][0][key]
            for key in ("resource_id", "revision", "content_hash")}, "role": "required",
            "admission": "explicitly_enabled", "authority": "synthetic", "token_count": None,
            "task_id": inputs["work_objective_id"]}]
        inputs["catalog"]["resources"] = []
        inputs["descriptions"] = []
    else:
        inputs["descriptions"] = []
    def planner(result):
        planned.append(result["status"])
        return host_plan(tmp_path, result, [])
    if status == "no_optional_guidance":
        result, tasks = runner.discover_jevdrill_work_units(adapter, inputs, plan_objective=planner)
        assert result["status"] == status and len(tasks) == 2 and planned == [status]
    else:
        with pytest.raises(JevDrillUnavailable) as rejected:
            runner.discover_jevdrill_work_units(adapter, inputs, plan_objective=planner)
        assert rejected.value.decision["status"] == status and planned == []
    assert "discover" in trace.read_text()


def test_objective_tombstone_survives_restart_and_preserves_reports(installed_discovery):
    from phase_loop_runtime.jevdrill_queue import ReportQueue
    adapter, inputs, _, _, _, _ = installed_discovery
    result = adapter.discover_objective(inputs)
    ref = {key: result["details"][key] for key in ("discovery_id", "work_objective_id", "trace_digest")}
    envelope = inputs["envelope"]
    with adapter.queue.objective_guard():
        adapter.queue.delete_objective(envelope["project_id"], envelope["workspace_id"], inputs["work_objective_id"])
    recovered = ReportQueue(adapter.queue.path, sanitize=adapter.sanitize_report)
    assert recovered.objective_deleted(envelope, inputs["work_objective_id"])
    assert not recovered.objective_bound(envelope, ref)
    assert not recovered.is_deleted(envelope["project_id"], envelope["workspace_id"], str(uuid4()))
    before = len(adapter.transport.storage.read_bytes())
    with pytest.raises(JevDrillUnavailable, match="deleted"):
        adapter.discover_objective(inputs)
    assert len(adapter.transport.storage.read_bytes()) == before


def test_native_unsupported_observer_records_unknown_capture(tmp_path, monkeypatch):
    from phase_loop_runtime import launcher
    from phase_loop_runtime.models import InjectionMetadata, PromptBundle
    import sys
    child = tmp_path / "synthetic.py"
    child.write_text("import sys\nfrom pathlib import Path\n"
                     "sys.stdin.read()\nprint('synthetic native execution')\n"
                     "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('complete')\n")
    bundle = PromptBundle("workflow", "synthetic", "stdin")
    spec = launcher.LaunchSpec(executor="codex", command=[sys.executable, str(child), "exec", "--json", "-"],
        prompt_bundle=bundle, injection_metadata=InjectionMetadata("codex", "stdin"),
        delivery_mode="stdin", dispatch_decision=None, available=True)
    entered = []
    original = launcher._codex_executor_input_manifest
    def observe(*args):
        entered.append("input_manifest")
        return original(*args)
    monkeypatch.setattr(launcher, "_codex_executor_input_manifest", observe)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True, codex_input_capture=True)
    assert result.returncode == 0 and "synthetic native execution" in result.output
    assert entered == ["input_manifest"]
    assert result.executor_input_manifest is None and result.jevdrill_usage is None
    assert result.jevdrill_protocol_diagnostics == {"capture": "disabled", "reason": "unsupported_path_or_probe"}
    assert result.event_metadata()["jevdrill_protocol_diagnostics"] == result.jevdrill_protocol_diagnostics
