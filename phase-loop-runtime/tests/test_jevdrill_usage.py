"""Synthetic local Codex protocol and adapter controls; no provider execution."""

import json
import os
import sys
import threading
import time
from copy import deepcopy
from dataclasses import replace
from queue import Queue
from types import SimpleNamespace

import pytest

from phase_loop_runtime import launcher
from phase_loop_runtime.launcher import LaunchResult, LaunchSpec, _CodexUsageCollector
from phase_loop_runtime.models import InjectionMetadata, PromptBundle
from test_jevdrill_adapter import adapter_fixture

# The launcher's documented off-Linux path: capture is requested but never
# probed or observed, and the launch otherwise proceeds unchanged.
DISABLED = {"capture": "disabled", "reason": "unsupported_path_or_probe"}

USAGE = {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 0,
         "reasoning_output_tokens": 5, "cache_write_input_tokens": 0}


def captures():
    """Evaluate the launcher's own capture-platform condition at test time."""
    return launcher.sys.platform.startswith("linux")


def assert_disabled(result):
    assert result.jevdrill_usage is None
    assert result.jevdrill_protocol_diagnostics == DISABLED


def assert_ordinary_bounded_launch(result):
    """Off Linux a short budget is an ordinary relative executor timeout."""
    assert_disabled(result)
    if result.timed_out:
        assert result.returncode == 124
    else:
        assert result.returncode == 0 and records()[-1] in result.output


def records(usage=None, middle=()):
    return [json.dumps({"type": "thread.started", "thread_id": "synthetic"}),
            '{"type":"turn.started"}', *middle,
            json.dumps({"type": "turn.completed", "usage": USAGE if usage is None else usage})]


def collect(lines):
    collector = _CodexUsageCollector()
    for line in lines:
        collector.observe(line)
    return collector.receipt()


def values(receipt):
    return {m["metric_id"]: m["measurement_value"] for m in receipt["measurements"]}


def synthetic_spec(tmp_path, monkeypatch, lines=None, *, version="codex-cli 0.159.2",
                   tail="", probe=""):
    child = tmp_path / "codex"
    child.write_text("#!" + sys.executable + "\nimport sys,os,time,signal,json\nfrom pathlib import Path\n"
        + "if '--version' in sys.argv:\n"
        + " " + (probe or "print(" + repr(version) + "); sys.exit(0)") + "\n"
        + "sys.stdin.read()\n"
        + "\n".join("print(" + repr(line) + ",flush=True)" for line in (records() if lines is None else lines))
        + "\n" + tail + "\n")
    child.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    bundle = PromptBundle("workflow", "SYNTHETIC_PRIVATE_TASK", "inline")
    command = ([sys.executable, str(child), "exec", "--json", bundle.render_context()]
               if os.name == "nt" else ["codex", "exec", "--json", bundle.render_context()])
    return LaunchSpec(executor="codex", command=command,
        prompt_bundle=bundle, injection_metadata=InjectionMetadata("codex", "inline"),
        delivery_mode="inline", dispatch_decision=None, available=True,
        selected_model="model-a", effective_effort="high", wrapped_cwd=str(tmp_path))


def test_supported_snapshot_and_opaque_web_duplicates():
    web = '{"type":"item.completed","item":{"id":"item_0","type":"web_search","id":"search_0","query":"PRIVATE_TOOL","action":{"type":"search","query":"PRIVATE_TOOL"}}}'
    receipt = collect(records(middle=[web]))
    assert values(receipt)["input_tokens"]["value"] == 100
    assert values(receipt)["cached_input_tokens"]["value"] == 0
    assert len(receipt["measurements"]) == 4
    assert "PRIVATE_TOOL" not in json.dumps(receipt)


@pytest.mark.parametrize("middle", [
    '{"type":"item.completed","item":{"id":"0","type":"mcp_tool_call","payload":{"type":"turn.completed","usage":{"input_tokens":999}}}}',
    '{"type":"item.completed","item":{"type":"error","message":"benign configuration warning"}}',
])
def test_opaque_tool_and_benign_warning(middle):
    assert values(collect(records(middle=[middle])))["input_tokens"]["value"] == 100


@pytest.mark.parametrize("middle", [
    'not protocol', '{"type":"item.completed","type":"turn.completed"}',
    '{"type":"item.completed","item":{"type":"agent_message","type":"web_search"}}',
    '{"type":"item.completed","item":{"type":"collab_tool_call"}}',
    '{"type":"item.completed","item":{"type":"error","message":"model rerouted: other"}}',
    '{"type":"item.completed","item":{"type":"error","message":"in-process app-server event stream lagged; dropped 4 events"}}',
    '{"type":"item.completed","item":{"type":"error","message":"ok","message":"hidden"}}',
    '{"type":"item.completed","item":{"type":"error","message":4}}',
    '{"type":"error","message":"failed to serialize exec json event: synthetic"}',
    '{"type":"turn.failed","error":{"message":"synthetic"}}',
    '{"type":"unknown"}', '{"type":"thread.started","thread_id":"second"}',
    '{"type":"turn.started"}', '{"type":"item.completed","item":NaN}',
    '{"type":"item.completed","item":{"type":"agent_message","content":1e999}}',
    pytest.param('x' * (1024 * 1024 + 1), id="oversized_line"), '{"type":"item.completed","item":{"type":"collab_tool_call",' ,
])
def test_permanent_invalidation(middle):
    assert collect(records(middle=[middle])) is None


@pytest.mark.parametrize("bad", [True, -1, 1.5, 2**53, float("nan"), float("inf")])
def test_invalid_counter(bad):
    usage = {**USAGE, "input_tokens": bad}
    assert collect(records(usage) + records()) is None


@pytest.mark.parametrize("usage", [
    {**USAGE, "cached_input_tokens": 101}, {**USAGE, "reasoning_output_tokens": 21},
    {"cached_input_tokens": 0}, {"reasoning_output_tokens": 0},
    {k: 0 for k in USAGE}, {},
])
def test_invalid_subsets_and_zero_fallback(usage):
    assert collect(records(usage)) is None


def test_missing_zero_and_portable_integer():
    receipt = collect(records({"input_tokens": 2**53-1, "output_tokens": 1}))
    assert values(receipt)["input_tokens"]["value"] == 2**53-1
    assert values(receipt)["cached_input_tokens"] == {"kind": "unknown", "reason": "not_reported"}
    assert values(collect(records()))["cached_input_tokens"] == {"kind": "known", "unit": "tokens", "value": 0}


def test_duplicate_usage_keys_and_terminals():
    duplicate = '{"type":"turn.completed","usage":{"input_tokens":100,"input_tokens":1,"output_tokens":2}}'
    assert collect(records()[:-1] + [duplicate] + records()) is None
    assert collect(records() + [records()[-1]]) is None
    assert collect(records()[:-1]) is None


def test_stdout_only_and_final_drain(tmp_path, monkeypatch):
    forged = json.dumps({"type": "turn.completed", "usage": {**USAGE, "input_tokens": 999}})
    spec = synthetic_spec(tmp_path, monkeypatch, tail="print(" + repr(forged) + ",file=sys.stderr,flush=True)")
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    if captures():
        assert values(result.jevdrill_usage)["input_tokens"]["value"] == 100
    else:
        assert_disabled(result)
    assert forged in result.output
    assert result.codex_turn_completion["completed"] is False
    assert "jevdrill_usage" not in result.event_metadata()
    assert launcher._result_with_spec(result, spec).jevdrill_usage == result.jevdrill_usage


def test_late_pipe_records_are_drained(tmp_path, monkeypatch):
    # Root exits first; its local descendant writes the terminal line before EOF.
    tail = "pid=os.fork() if hasattr(os,'fork') else 1\nif pid==0:\n time.sleep(.15); print(" + repr(records()[-1]) + ",flush=True); os._exit(0)\nos._exit(0)"
    spec = synthetic_spec(tmp_path, monkeypatch, lines=records()[:-1], tail=tail)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    if captures():
        assert values(result.jevdrill_usage)["input_tokens"]["value"] == 100
    else:
        # Without the observer the ordinary launcher keeps the root's output only.
        assert_disabled(result)
        assert result.returncode == 0 and records()[0] in result.output


def test_incomplete_drain_is_unknown_and_bounded(tmp_path, monkeypatch):
    tail = "pid=os.fork() if hasattr(os,'fork') else 1\nif pid==0:\n time.sleep(2); os._exit(0)\nos._exit(0)"
    spec = synthetic_spec(tmp_path, monkeypatch, tail=tail)
    started = time.monotonic()
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert result.jevdrill_usage is None
    if captures():
        assert time.monotonic() - started < 1.8
    else:
        assert_disabled(result)
        assert result.returncode == 0 and records()[-1] in result.output


@pytest.mark.parametrize("case", ["invalid_utf8", "reader_error"])
def test_reader_error_is_distinct_from_eof(tmp_path, case):
    read_fd, write_fd = os.pipe()
    queue = Queue()
    pipe = os.fdopen(read_fd, "rb")
    if case == "invalid_utf8":
        os.write(write_fd, b"\xff\n")
    else:
        pipe.close()
    os.close(write_fd)
    launcher._read_usage_lines(pipe, queue, "stdout", threading.Event())
    entries = list(queue.queue)
    assert any(row[1] == "error" for row in entries)
    if case == "reader_error":
        assert not any(row[1] == "eof" for row in entries)
    pipe.close()


@pytest.mark.parametrize("version", ["codex-cli 0.159.1", "unrecognized"])
def test_unsupported_version(tmp_path, monkeypatch, version):
    spec = synthetic_spec(tmp_path, monkeypatch, version=version)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert result.returncode == 0
    assert result.jevdrill_usage is None


def test_nonadapter_json_does_not_probe_or_split(tmp_path, monkeypatch):
    spec = synthetic_spec(tmp_path, monkeypatch, tail="print('STDERR_SYNTHETIC',file=sys.stderr)")
    monkeypatch.setattr(launcher, "_codex_usage_version", lambda *_: pytest.fail("probe forbidden"))
    result = launcher.launch_with_spec(spec)
    assert "STDERR_SYNTHETIC" in result.output
    assert result.jevdrill_usage is None


@pytest.mark.parametrize("case", ["dry", "resume", "fork", "other_executor", "other_platform"])
def test_capture_structural_exclusions(tmp_path, monkeypatch, case):
    spec = synthetic_spec(tmp_path, monkeypatch)
    if case in ("resume", "fork"):
        spec = replace(spec, command=[*spec.command[:2], case, *spec.command[2:]])
    elif case == "other_executor":
        spec = replace(spec, executor="command")
    elif case == "other_platform":
        monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setattr(launcher, "_codex_usage_version", lambda *_: pytest.fail("probe forbidden"))
    result = launcher.launch_with_spec(spec, dry_run=case == "dry", codex_usage_capture=True)
    assert result.jevdrill_usage is None


def test_probe_descendant_cleanup_and_deadline(tmp_path, monkeypatch):
    marker = tmp_path / "descendant"
    probe = "pid=os.fork(); (Path(" + repr(str(marker)) + ").write_text(str(pid)) if pid else None); time.sleep(5); sys.exit(0)"
    spec = synthetic_spec(tmp_path, monkeypatch, probe=probe)
    started = time.monotonic()
    result = launcher.launch_with_spec(replace(spec, launch_timeout_seconds=.2), codex_usage_capture=True)
    if not captures():
        # No probe is started, so no probe descendant exists; the executor runs.
        assert not marker.exists()
        assert_ordinary_bounded_launch(result)
        return
    assert result.timed_out
    assert result.returncode == 124
    assert result.output == ""
    assert time.monotonic() - started < 1
    pid = int(marker.read_text())
    stat = __import__("pathlib").Path("/proc") / str(pid) / "stat"
    deadline = time.monotonic() + .3
    while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
        time.sleep(.01)
    assert not stat.exists() or stat.read_text().split()[2] == "Z"


@pytest.mark.parametrize("stream", [1, 2])
def test_real_decode_failure_stays_unknown(tmp_path, monkeypatch, stream):
    spec = synthetic_spec(tmp_path, monkeypatch, tail="os.write(" + str(stream) + ",b'\\xff\\n')")
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert result.returncode == 0 and result.jevdrill_usage is None


def test_observer_survives_lease_recursion(tmp_path, monkeypatch):
    fd = os.open(tmp_path / "lease", os.O_CREAT | os.O_RDWR, 0o600)
    if os.name == "posix":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
    authority = SimpleNamespace(fileno=lambda: fd, generation="synthetic", identity=None)
    try:
        spec = synthetic_spec(tmp_path, monkeypatch)
        result = launcher.launch_with_spec(spec, codex_usage_capture=True, lease_authority=authority)
        if captures():
            assert result.returncode == 0 and result.supervisor_receipt is not None
            assert values(result.jevdrill_usage)["input_tokens"]["value"] == 100
        elif launcher.sys.platform == "darwin":
            # Native macOS refuses leased execution before any dispatch.
            assert_disabled(result)
            assert result.returncode == 1 and result.supervisor_receipt is None
            assert result.process_pid is None
            assert "Run leased worktree execution on a Linux worker." in result.output
        else:
            assert_disabled(result)
    finally:
        os.close(fd)


def test_cancel_drains_valid_observation(tmp_path, monkeypatch):
    tail = "signal.signal(signal.SIGTERM,lambda *_: sys.exit(0)); time.sleep(.15); os.kill(os.getppid(),signal.SIGINT); time.sleep(10)"
    if os.name == "nt":
        # No POSIX signal reaches the launcher from the job-owned child, so the
        # operator's interrupt is raised in the launcher once the child has started.
        tail = "Path(sys.argv[0]).with_name('started').touch(); time.sleep(10)"
        launched = threading.Event()
        def interrupt():
            deadline = time.monotonic() + 10
            while not (tmp_path / "started").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            time.sleep(.15)
            if (tmp_path / "started").exists() and not launched.is_set():
                import _thread
                _thread.interrupt_main()
        threading.Thread(target=interrupt, daemon=True).start()
    spec = synthetic_spec(tmp_path, monkeypatch, tail=tail)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    if os.name == "nt":
        launched.set()
    # The job object ends the tree on Windows, so no graceful SIGTERM exit status.
    assert result.interrupted and result.returncode == (130 if os.name == "nt" else 0)
    if captures():
        assert values(result.jevdrill_usage)["input_tokens"]["value"] == 100
    else:
        assert_disabled(result)


def test_probe_failure_preserves_executor(tmp_path, monkeypatch):
    spec = synthetic_spec(tmp_path, monkeypatch, probe="sys.exit(2)")
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert result.returncode == 0 and result.jevdrill_usage is None


def test_probe_cancellation_does_not_dispatch(tmp_path, monkeypatch):
    probe = "time.sleep(.1); os.kill(os.getppid(),signal.SIGINT); time.sleep(10)"
    spec = synthetic_spec(tmp_path, monkeypatch, probe=probe)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    if captures():
        assert result.interrupted and result.returncode == 130
        assert result.output == "" and result.jevdrill_usage is None
    else:
        # The cancelling probe is never started; the executor runs normally.
        assert_disabled(result)
        assert not result.interrupted and result.returncode == 0
        assert records()[-1] in result.output


def test_probe_and_dispatch_share_actual_environment(tmp_path, monkeypatch):
    probe = "assert os.environ['PHASE_LOOP_CALLER_RUN_ID']=='synthetic'; assert os.environ['PHASE_LOOP_CHILD']=='1'; print('codex-cli 0.159.2'); sys.exit(0)"
    tail = "assert os.environ['PHASE_LOOP_CALLER_RUN_ID']=='synthetic'; assert os.environ['PHASE_LOOP_CHILD']=='1'"
    spec = synthetic_spec(tmp_path, monkeypatch, probe=probe, tail=tail)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True, caller_run_id="synthetic")
    assert result.returncode == 0
    if captures():
        assert values(result.jevdrill_usage)["input_tokens"]["value"] == 100
    else:
        # The dispatch-side environment assertions still ran; no probe did.
        assert_disabled(result)
        assert records()[-1] in result.output


def test_launch_preparation_cannot_extend_deadline(tmp_path, monkeypatch):
    spec = synthetic_spec(tmp_path, monkeypatch)
    def delayed_snapshot(_):
        time.sleep(.2)
        return None
    monkeypatch.setattr(launcher, "_worktree_change_snapshot", delayed_snapshot)
    result = launcher.launch_with_spec(replace(spec, launch_timeout_seconds=.1), codex_usage_capture=True)
    if captures():
        assert result.timed_out and result.returncode == 124
        assert result.output == "" and result.process_pid is None
    else:
        # The absolute launch deadline is anchored only on the capture path; off
        # Linux the ordinary relative timeout applies to the dispatched executor.
        assert_ordinary_bounded_launch(result)


@pytest.mark.parametrize("terminal", ["nonzero", "timeout", "stall", "interrupted"])
def test_adapter_observed_failure_retains_identity(tmp_path, monkeypatch, terminal):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    tail = "sys.exit(3)" if terminal == "nonzero" else ""
    if terminal in ("timeout", "stall"):
        tail = "signal.signal(signal.SIGTERM,lambda *_: sys.exit(0)); time.sleep(10)"
    spec = synthetic_spec(tmp_path, monkeypatch, tail=tail)
    spec = replace(spec, prompt_bundle=prepared["prompt_bundle"],
                   launch_timeout_seconds=.2 if terminal == "timeout" else None)
    if terminal == "stall":
        original = launcher.run_heartbeat_summary
        def heartbeat(**kw):
            result = original(**kw)
            result["stalled_suspect"] = result.get("elapsed_seconds", 0) >= .1
            return result
        monkeypatch.setattr(launcher, "run_heartbeat_summary", heartbeat)
    launch_kwargs = {"heartbeat_interval_seconds": 0} if terminal == "stall" else {}
    launch = launcher.launch_with_spec
    if terminal == "interrupted":
        launch = lambda spec, **kw: LaunchResult(command=["synthetic"], returncode=0, interrupted=True,
                                                jevdrill_usage=collect(records()))
    result = adapter.launch(launch, spec, **launch_kwargs)
    for _ in range(3):
        adapter.flush()
    reports = [r["event"]["payload"] for command, r in calls if command == "report"]
    assert reports[1]["event_type"] == ("canceled" if terminal == "interrupted" else "failed")
    assert result.jevdrill_execution_run["applied_plan_id"] == result.jevdrill_execution_run["selected_plan_id"]
    usage = [r for r in reports if r["kind"] == "usage"]
    assert len(usage) == 1
    if captures() or terminal == "interrupted":
        assert values(usage[0])["input_tokens"]["value"] == 100
    else:
        # Off Linux the lifecycle and usage report survive with unknown counters.
        assert all(m["measurement_value"] == {"kind": "unknown", "reason": "not_reported"}
                   for m in usage[0]["measurements"][1:5])
    if terminal in ("timeout", "stall"):
        # Native Windows has no SIGTERM handler to run: the job object ends the tree.
        assert result.returncode == ({"timeout": 124, "stall": 1}[terminal] if os.name == "nt" else 0)


@pytest.mark.parametrize("method", ["codex_exec_jsonl_0_159_2_v1", "codex_exec_jsonl_0_159_2_v2"])
@pytest.mark.parametrize("damage", ["field", "method", "mixed_methods", "subset", "bool", "fraction", "all_zero", "duplicate"])
def test_adapter_rejects_receipt_without_losing_lifecycle(tmp_path, damage, method):
    adapter, _, _, kwargs, calls, notices = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    receipt = deepcopy(collect(records()))
    for row in receipt["measurements"]:
        row["method"] = method
    if damage == "field":
        receipt["private_output"] = "SENTINEL"
    elif damage == "duplicate":
        receipt["measurements"].append(receipt["measurements"][0])
    elif damage == "all_zero":
        for m in receipt["measurements"]:
            m["measurement_value"]["value"] = 0
    elif damage == "mixed_methods":
        receipt["measurements"][0]["method"] = "codex_exec_jsonl_0_159_2_v2" if method.endswith("v1") else "codex_exec_jsonl_0_159_2_v1"
    else:
        row = receipt["measurements"][2 if damage == "subset" else 0]
        if damage == "method":
            row["method"] = "unregistered"
        else:
            row["measurement_value"]["value"] = {"subset": 101, "bool": True, "fraction": 1.5}[damage]
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"],
                           selected_model="model-a", effective_effort="high", claude_route=None)
    result = adapter.launch(lambda *a, **k: LaunchResult(command=["synthetic"], returncode=0, jevdrill_usage=receipt), spec)
    for _ in range(3):
        adapter.flush()
    reports = [r["event"]["payload"] for c, r in calls if c == "report"]
    assert result.returncode == 0 and reports[1]["event_type"] == "completed"
    assert all(m["measurement_value"]["kind"] == "unknown" for m in reports[2]["measurements"][1:])
    assert any(n.get("status") == "invalid_usage_receipt" for n in notices)


@pytest.mark.parametrize("method", ["codex_exec_jsonl_0_159_2_v1", "codex_exec_jsonl_0_159_2_v2"])
def test_adapter_preserves_registered_method_for_legacy_and_current_receipts(tmp_path, method):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    receipt = deepcopy(collect(records()))
    for row in receipt["measurements"]:
        row["method"] = method
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"], selected_model="model-a", effective_effort="high", claude_route=None)
    result = adapter.launch(lambda *a, **k: LaunchResult(command=["synthetic"], returncode=0, jevdrill_usage=receipt), spec)
    for _ in range(3):
        adapter.flush()
    usage = [r["event"]["payload"] for c, r in calls if c == "report" and r["event"]["payload"]["kind"] == "usage"]
    assert result.returncode == 0 and len(usage) == 1
    assert usage[0]["measurements"][1:5] == receipt["measurements"]


def test_usage_delivery_retry_has_stable_identity(tmp_path):
    adapter, _, _, kwargs, calls, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = SimpleNamespace(executor="codex", prompt_bundle=prepared["prompt_bundle"],
                           selected_model="model-a", effective_effort="high", claude_route=None)
    receipt = collect(records())
    adapter.launch(lambda *a, **k: LaunchResult(command=["synthetic"], returncode=0, jevdrill_usage=receipt), spec)
    adapter.flush()
    original = adapter.transport.call
    lost = []
    def deliver(command, payload, **kwargs):
        response = original(command, payload, **kwargs)
        if command == "report" and not lost:
            lost.append(payload["event"]["event_id"])
            raise TimeoutError("synthetic lost acknowledgment")
        return response
    adapter.transport.call = deliver
    adapter.flush()
    adapter.queue.clock = lambda: time.time() + 10
    adapter.flush()
    usage_ids = [r["event"]["event_id"] for c, r in calls if c == "report" and r["event"]["payload"]["kind"] == "usage"]
    assert len(usage_ids) == 2 and usage_ids[0] == usage_ids[1]
