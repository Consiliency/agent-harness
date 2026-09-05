"""Exited children must not turn interim progress into another execute dispatch."""

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime.launcher import (
    AuthPreflightResult, LaunchResult, build_launch_request, build_launch_spec, launch,
)
from phase_loop_runtime.models import CLOSEOUT_SCHEMA
from phase_loop_runtime.profiles import resolve_profile
from phase_loop_runtime.prompts import build_prompt
from phase_loop_runtime.runner import _parsed_child_automation, run_loop
from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, make_repo, write_phase_plan


@pytest.fixture(autouse=True)
def _standalone_skill_resolution(monkeypatch):
    monkeypatch.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs", lambda *a, **k: {})


def _payload(status="executing"):
    return {
        "terminal_status": status,
        "verification_status": "not_run" if status == "executing" else "passed",
        "dirty_paths": [],
        "produced_if_gates": [] if status == "executing" else ["IF-0-CONTRACT-1"],
        "next_action": "Continue working" if status == "executing" else None,
        "blocker_class": None, "blocker_summary": None, "human_required": None,
        "required_human_inputs": [],
    }


def _spec(repo, roadmap, action="execute"):
    plan = repo / "plans" / "phase-plan-v1-CONTRACT.md"
    return build_launch_spec(build_launch_request(
        executor="codex", action=action, repo=repo, roadmap=roadmap,
        phase="CONTRACT", plan=plan, model_selection=resolve_profile(action),
        prompt_bundle=build_prompt(action, roadmap, phase="CONTRACT", plan=plan),
        json_output=True, bypass_approvals=False,
    ))


@pytest.mark.parametrize("action", ["execute", "repair", "review"])
def test_final_response_schema_excludes_interim_without_changing_lifecycle(tmp_path, action):
    spec = _spec(tmp_path, tmp_path / "roadmap.md", action)
    assert "executing" not in spec.codex_output_schema["properties"]["terminal_status"]["enum"]
    assert "executing" in CLOSEOUT_SCHEMA["properties"]["terminal_status"]["enum"]


def test_golden_delta_is_only_final_schema_exclusion():
    golden = json.loads((Path(__file__).parent / "data/launchspec_golden/launchspec_golden.json").read_text())
    command = golden["claude_print_solo"]["command"]
    index = command.index("--json-schema") + 1
    schema = json.loads(command[index])
    statuses = schema["properties"]["terminal_status"]["enum"]
    assert "executing" not in statuses
    statuses.insert(2, "executing")
    command[index] = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    # Historical INPUT, not regenerated candidate output: the normalized golden
    # at e7350e534e9a369be45baf34dc812eadd873e1f5. Undoing the sole permitted
    # enum exclusion must recover it, including every prompt/hash/model/argv.
    canonical = json.dumps(golden, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == "4026eb47167dcb4b495ae273f82f77f0ba20085508abf702aa89d5dbd3483ecc"


@pytest.mark.parametrize("stream", [False, True])
def test_interim_only_exit_is_closeout_failure(tmp_path, stream):
    spec = _spec(tmp_path, tmp_path / "roadmap.md")
    output = json.dumps(_payload())
    if stream:
        output = json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": output,
        }})
    result = LaunchResult(command=spec.command, returncode=0, output=output)
    parsed = _parsed_child_automation(result, spec)
    assert parsed["automation_status"] == "blocked"
    assert parsed["automation_blocker_class"] == "contract_bug"
    assert parsed["native_closeout_extraction_failure"]["reason"] == "executor_exited_without_closeout"
    assert "native_closeout_payload" not in parsed


def test_interim_followed_by_final_closeout_is_accepted(tmp_path):
    spec = _spec(tmp_path, tmp_path / "roadmap.md")
    output = "\n".join(json.dumps(p) for p in (_payload(), _payload("complete")))
    parsed = _parsed_child_automation(LaunchResult(command=spec.command, returncode=0, output=output), spec)
    assert parsed["automation_status"] == "complete"


def test_legacy_interim_exit_is_also_rejected(tmp_path):
    spec = _spec(tmp_path, tmp_path / "roadmap.md")
    output = build_fake_automation_output(status="executing", verification_status="not_run")
    parsed = _parsed_child_automation(LaunchResult(command=spec.command, returncode=0, output=output), spec)
    assert parsed["automation_status"] == "blocked"
    assert parsed["automation_blocker_class"] == "contract_bug"


@pytest.mark.parametrize("status", ["executed", "awaiting_phase_closeout", "planned"])
def test_legitimate_handoff_closeouts_remain_accepted(tmp_path, status):
    spec = _spec(tmp_path, tmp_path / "roadmap.md")
    payload = _payload(status)
    if status == "planned":
        payload["verification_status"] = "not_run"
    parsed = _parsed_child_automation(LaunchResult(command=spec.command, returncode=0, output=json.dumps(payload)), spec)
    assert parsed["automation_status"] == status


def test_dry_run_is_not_misreported_as_exited_child(tmp_path):
    spec = _spec(tmp_path, tmp_path / "roadmap.md")
    result = LaunchResult(command=spec.command, returncode=None, dry_run=True, output="")
    assert not _parsed_child_automation(result, spec)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_exited_child_blocks_once_and_persists_actual_returncode(tmp_path, monkeypatch, exit_code):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "CONTRACT", roadmap)
    commit_fixture_paths(repo, "fixture plan", plan)
    calls = []

    def exited_child(spec, **kwargs):
        calls.append(spec)
        output = json.dumps(_payload())
        result = launch(
            [sys.executable, "-c", f"import sys; print({output!r}); sys.exit({exit_code})"],
            log_path=kwargs.get("log_path"),
        )
        assert result.returncode == exit_code
        return replace(result, executor=spec.executor, changed_paths=())

    monkeypatch.setattr("phase_loop_runtime.runner.run_auth_preflight", lambda *a, **k: AuthPreflightResult(ok=True, metadata={}))
    monkeypatch.setattr("phase_loop_runtime.runner.launch_with_spec", exited_child)
    snapshot, _ = run_loop(repo, roadmap, phase="CONTRACT", executor="codex", observe=True)
    assert len(calls) == 1
    assert snapshot.phases["CONTRACT"] == "blocked"
    launches = list((repo / ".phase-loop" / "runs").glob("*/launch.json"))
    assert len(launches) == 1
    metadata = json.loads(launches[0].read_text())
    assert metadata["returncode"] == exit_code
    if exit_code == 0:
        assert snapshot.blocker_class == "contract_bug"
        assert "exited without a terminal closeout" in snapshot.blocker_summary
        terminal = json.loads((launches[0].parent / "terminal-summary.json").read_text())
        assert terminal["terminal_status"] == "blocked"
        assert terminal["verification_status"] == "blocked"
