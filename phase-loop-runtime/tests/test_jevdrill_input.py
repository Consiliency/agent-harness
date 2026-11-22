"""Resolved submission controls using local fake executors, without providers."""

import hashlib
import json
import sys
from dataclasses import replace

import pytest

from phase_loop_runtime import launcher
from phase_loop_runtime.models import InjectionMetadata, PromptBundle
from phase_loop_runtime.observability import merge_launch_metadata, read_launch_metadata
from test_jevdrill_adapter import adapter_fixture


def component(data):
    return {"byte_count": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def input_spec(tmp_path):
    child = tmp_path / "codex"
    child.write_text("#!" + sys.executable + "\n"
        "import sys,json,hashlib\nfrom pathlib import Path\n"
        "data=sys.stdin.buffer.read()\n"
        "parts={'prompt':{'byte_count':len(data),'sha256':hashlib.sha256(data).hexdigest()}}\n"
        "if '--output-schema' in sys.argv:\n"
        " data=Path(sys.argv[sys.argv.index('--output-schema')+1]).read_bytes()\n"
        " parts['output_schema']={'byte_count':len(data),'sha256':hashlib.sha256(data).hexdigest()}\n"
        "print(json.dumps(parts))\n"
        "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('complete')\n")
    child.chmod(0o700)
    bundle = PromptBundle("workflow", "PRIVATE_PROMPT é😀\r\nnext", "prompt_only",
                          context_body="PRIVATE_CONTEXT with additional instructions")
    return launcher.LaunchSpec(executor="codex", command=[str(child), "exec", bundle.render_prompt()],
        prompt_bundle=bundle, injection_metadata=InjectionMetadata("codex", "prompt_only",
            context_sha256=bundle.context_sha256()), delivery_mode="prompt_only",
        dispatch_decision=None, available=True)


@pytest.mark.parametrize("schema", [False, True])
def test_manifest_matches_child_bytes_and_preserves_context(tmp_path, schema):
    spec = input_spec(tmp_path)
    if schema:
        spec = replace(spec, command=[*spec.command[:-1], "--output-schema",
                       launcher.CODEX_OUTPUT_SCHEMA_PLACEHOLDER, spec.command[-1]],
                       codex_output_schema={"type": "object", "description": "PRIVATE_SCHEMA é"})
    result = launcher.launch_with_spec(spec, codex_input_capture=True,
                                       log_path=tmp_path / "run/output.log")
    received = json.loads(result.output)
    manifest = result.executor_input_manifest
    assert result.returncode == 0 and result.codex_turn_completion["completed"]
    assert manifest["prompt"] == received["prompt"]
    assert manifest["prompt"] == component(spec.prompt_bundle.render_prompt().encode("utf-8"))
    assert manifest["prompt"]["byte_count"] != len(spec.prompt_bundle.render_prompt())
    assert result.context_sha256 == spec.prompt_bundle.context_sha256()
    assert manifest["prompt"]["sha256"] != result.context_sha256
    assert manifest["output_schema"] == received.get("output_schema")
    assert manifest["output_schema_status"] == ("observed" if schema else "not_supplied")
    assert manifest["provider_context"] == manifest["provider_receipt"] == "unknown"
    assert manifest["scope"] == "prepared_submission"
    assert not (tmp_path / "run/codex-output-schema.json").exists()
    assert "PRIVATE_" not in json.dumps(manifest)
    assert str(tmp_path) not in json.dumps(manifest)
    path = tmp_path / "launch.json"
    merge_launch_metadata(path, result.event_metadata())
    assert read_launch_metadata(path)["executor_input_manifest"] == manifest


@pytest.mark.parametrize("mode", ["prompt_only", "inline", "stdin"])
def test_delivery_modes_use_the_resolved_payload(tmp_path, mode):
    spec = input_spec(tmp_path)
    spec = replace(spec, delivery_mode=mode)
    spec = replace(spec, command=[*spec.command[:-1], spec.delivery_payload()])
    result = launcher.launch_with_spec(spec, codex_input_capture=True)
    assert result.executor_input_manifest["prompt"] == json.loads(result.output)["prompt"]


def test_external_schema_is_not_read_for_accounting(tmp_path, monkeypatch):
    spec = input_spec(tmp_path)
    spec = replace(spec, command=[*spec.command[:-1], "--output-schema", "/private/external", "-"])
    reads = []
    monkeypatch.setattr(launcher.Path, "read_bytes", lambda path: reads.append(path))
    manifest = launcher._codex_executor_input_manifest(spec, spec.command, spec.delivery_payload())
    assert not reads
    assert manifest["output_schema"] is None
    assert manifest["output_schema_status"] == "unknown"


def test_unreadable_owned_schema_stays_unknown(tmp_path, monkeypatch):
    spec = input_spec(tmp_path)
    spec = replace(spec, command=[*spec.command[:-1], "--output-schema",
                   launcher.CODEX_OUTPUT_SCHEMA_PLACEHOLDER, "-"], codex_output_schema={})
    def fail(path):
        raise OSError("synthetic read failure")
    monkeypatch.setattr(launcher.Path, "read_bytes", fail)
    manifest = launcher._codex_executor_input_manifest(spec, spec.command, spec.delivery_payload())
    assert manifest["output_schema"] is None and manifest["output_schema_status"] == "unknown"


@pytest.mark.parametrize("case", ["ordinary", "dry", "darwin", "resume", "fork", "context_file", "mismatch", "other"])
def test_unsupported_paths_do_not_claim_input(tmp_path, monkeypatch, case):
    spec = input_spec(tmp_path)
    if case == "darwin":
        monkeypatch.setattr(launcher.sys, "platform", "darwin")
    elif case in {"resume", "fork"}:
        spec = replace(spec, command=[*spec.command[:-1], case, spec.command[-1]])
    elif case == "context_file":
        spec = replace(spec, delivery_mode="context_file")
    elif case == "mismatch":
        spec = replace(spec, command=[*spec.command[:-1], "PRIVATE_DIFFERENT_PROMPT"])
    elif case == "other":
        spec = replace(spec, executor="claude")
    # Unsupported shapes can retain ordinary launch behavior; avoid invoking
    # the fake child with an argv prompt while it expects stdin.
    if case not in {"ordinary", "dry"}:
        monkeypatch.setattr(launcher, "launch", lambda command, **kwargs:
            launcher.LaunchResult(command=command, returncode=0))
    result = launcher.launch_with_spec(spec, dry_run=case == "dry", codex_input_capture=case != "ordinary")
    assert result.executor_input_manifest is None
    assert "executor_input_manifest" not in result.event_metadata()


def test_pre_dispatch_timeout_never_claims_provider_receipt(tmp_path, monkeypatch):
    spec = replace(input_spec(tmp_path), launch_timeout_seconds=0)
    def forbidden(*args, **kwargs):
        pytest.fail("executor must not dispatch")
    monkeypatch.setattr(launcher, "launch", forbidden)
    result = launcher.launch_with_spec(spec, codex_input_capture=True)
    assert result.timed_out
    assert result.executor_input_manifest["scope"] == "prepared_submission"
    assert result.executor_input_manifest["provider_receipt"] == "unknown"


def test_adapter_requests_capture_and_preserves_manifest(tmp_path):
    adapter, _, _, kwargs, _, _ = adapter_fixture(tmp_path)
    prepared = adapter.prepare(mode="main", dry_run=False, **kwargs)
    spec = replace(input_spec(tmp_path), prompt_bundle=prepared["prompt_bundle"],
                   selected_model="model-a", effective_effort="high")
    manifest = {"method": "codex_executor_input_v1", "scope": "prepared_submission"}
    def execute(spec, **flags):
        assert flags["codex_input_capture"] is True
        assert flags["codex_usage_capture"] is True
        return launcher.LaunchResult(command=spec.command, returncode=0, executor_input_manifest=manifest)
    result = adapter.launch(execute, spec)
    assert result.executor_input_manifest == manifest
    assert result.jevdrill_execution_run is not None
