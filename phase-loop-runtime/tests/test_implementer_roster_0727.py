"""The 0.7.27 implementer roster (maintainer ruling 2026-10-14).

Implementation (execute / repair, the ``implementer`` class) runs on
``gemini-3.8-flash`` at high, ``gpt-6.1-sol`` at medium, ``claude-sonnet-5-5`` at
medium and ``grok-4.7`` at high. The Gemini worker runs ``gemini-3.8-flash-high``.
The roster must hold on BOTH resolution paths -- the executor defaults
(``resolve_profile_for_executor``) and the runner's shipped model policy -- and must be
LAUNCHED (the rendered argv), not only spelled (agent-harness#777). Planning, review,
the other workers and explicit operator models are unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Imported before phase_loop_runtime: it pins the skill-source root the runner seam needs.
from phase_loop_test_utils import make_repo, write_phase_plan

from phase_loop_runtime import profiles
from phase_loop_runtime.launcher import build_launch_request, build_launch_spec
from phase_loop_runtime.prompts import build_prompt

ROSTER = {  # model-id-source: test pins the 0.7.27 implementer roster under test
    "gemini": ("gemini-3.8-flash", "high"),
    "codex": ("gpt-6.1-sol", "medium"),
    "claude": ("claude-sonnet-5-5", "medium"),
    "grok": ("grok-4.7", "high"),
}
ARGV = {  # model-id-source: test pins the rendered provider argv
    "gemini": ["--model", "gemini-3.8-flash-high"],
    "codex": ["--model", "gpt-6.1-sol", "-c", 'model_reasoning_effort="medium"'],
    "claude": ["--model", "claude-sonnet-5-5", "--effort", "medium"],
    "grok": ["-m", "grok-4.7", "--reasoning-effort", "high"],
}
ROADMAP = Path("/repo/specs/phase-plans-v1.md")
PLAN = Path("/repo/plans/phase-plan-v1-RUNNER.md")


def _shipped(executor, action, **kw):
    selection = profiles.resolve_profile_for_executor(action=action, executor=executor, **kw)
    return profiles.resolve_execution_policy(
        action=action, executor=executor, model_selection=selection,
        operator_model=kw.get("model"), operator_effort=kw.get("effort"),
        model_policy_rule=profiles.shipped_model_policy_rule(action, executor),
    )


def _argv(executor, selection):
    spec = build_launch_spec(build_launch_request(
        executor=executor, action="execute", repo=Path("/repo"), roadmap=ROADMAP, phase="RUNNER",
        plan=PLAN, model_selection=selection,
        prompt_bundle=build_prompt("execute", ROADMAP, phase="RUNNER", plan=PLAN, harness_target=executor),
        json_output=False, bypass_approvals=False,
    ))
    return spec.command


def _contains(argv, run):
    return any(argv[i:i + len(run)] == run for i in range(len(argv)))


@pytest.mark.parametrize("executor", sorted(ROSTER))
@pytest.mark.parametrize("action", ["execute", "repair"])
def test_executor_default_path_runs_the_roster(executor, action):
    selection = profiles.resolve_profile_for_executor(action=action, executor=executor)
    assert (selection.model, selection.effort) == ROSTER[executor]


@pytest.mark.parametrize("executor", sorted(ROSTER))
@pytest.mark.parametrize("action", ["execute", "repair"])
def test_runner_shipped_policy_runs_the_roster(executor, action):
    policy = _shipped(executor, action)
    assert (policy.model, policy.effort, policy.model_class) == (*ROSTER[executor], "implementer")


@pytest.mark.parametrize("executor", sorted(ROSTER))
def test_implementer_class_is_the_roster_model(executor):
    assert profiles.resolve_model_class(executor, "implementer") == ROSTER[executor][0]


def test_workers():
    assert profiles.resolve_model_class("gemini", "worker") == "gemini-3.8-flash-high"
    assert profiles.resolve_model_class("codex", "worker") == "gpt-5.6-luna"
    assert profiles.resolve_model_class("claude", "worker") == "claude-haiku-4-5-20251001"
    assert profiles.resolve_model_class("grok", "worker") == "grok-4.7"


@pytest.mark.parametrize("executor", sorted(ROSTER))
def test_execute_launch_argv_carries_the_roster(executor, monkeypatch):
    # Agent View is the Claude route that binds --model (Channel inherits the session).
    monkeypatch.setenv("PHASE_LOOP_CLAUDE_ROUTE", "agent_view")
    argv = _argv(executor, profiles.resolve_profile_for_executor(action="execute", executor=executor))
    assert _contains(argv, ARGV[executor]), argv


@pytest.mark.parametrize(("executor", "action", "expected"), [
    ("gemini", "plan", ("pro", "high")),
    ("gemini", "review", ("pro", "high")),
    ("codex", "plan", ("gpt-6-astra", "high")),
    ("codex", "review", ("gpt-6-astra", "high")),
    ("claude", "plan", ("claude-opus-5", "max")),
    ("claude", "review", ("claude-opus-5-5", "max")),
    ("grok", "plan", ("grok-4.7", "high")),
    ("opencode", "execute", ("openai/gpt-5.6-terra", "medium")),
])
def test_planning_review_and_opencode_routes_are_unchanged(executor, action, expected):
    selection = profiles.resolve_profile_for_executor(action=action, executor=executor)
    assert (selection.model, selection.effort) == expected


def test_shipped_policy_without_an_executor_keeps_its_effort():
    assert profiles.shipped_model_policy_rule("execute").effort == "high"
    assert profiles.shipped_model_policy_rule("execute", "opencode").effort == "high"
    assert profiles.shipped_model_policy_rule("plan", "codex").effort == "max"


@pytest.mark.parametrize(("executor", "model", "effort", "run"), [
    ("gemini", "gemini-3.5-flash-high", "high", ["--model", "gemini-3.5-flash-high"]),
    ("gemini", "gemini-3.8-flash", "medium", ["--model", "gemini-3.8-flash-medium"]),
    ("codex", "gpt-5.6-terra", "high", ["--model", "gpt-5.6-terra", "-c", 'model_reasoning_effort="high"']),
    ("claude", "claude-sonnet-5", "high", ["--model", "claude-sonnet-5", "--effort", "high"]),
])
def test_explicit_operator_settings_still_win(executor, model, effort, run, monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_CLAUDE_ROUTE", "agent_view")
    policy = _shipped(executor, "execute", model=model, effort=effort)
    assert (policy.model, policy.effort) == (model, effort)
    selection = profiles.resolve_profile_for_executor(action="execute", executor=executor, model=model, effort=effort)
    assert _contains(_argv(executor, selection), run)


class _Resolved(Exception):
    pass


@pytest.mark.parametrize("executor", sorted(ROSTER))
def test_runner_seam_resolves_the_roster(executor, tmp_path):
    # The runner's own seam (runner.run_loop -> resolve_execution_policy with the shipped
    # rule), not just the helpers. The resolution is captured and the run stops there,
    # before prompt assembly (which needs a skill-source tree this suite may not have).
    import subprocess
    from unittest.mock import patch

    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "RUNNER", roadmap)
    subprocess.run(["git", "add", str(plan.relative_to(repo))], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add runner plan"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
    resolved = []
    real = runner.resolve_execution_policy

    def capture(**kwargs):
        policy = real(**kwargs)
        resolved.append((policy.action, policy.model, policy.effort))
        raise _Resolved

    with patch("phase_loop_runtime.runner.run_auth_preflight",
               return_value=type("Preflight", (), {"ok": True, "metadata": {"probes": []}})()), \
            patch("phase_loop_runtime.runner.resolve_execution_policy", side_effect=capture), \
            pytest.raises(_Resolved):
        runner.run_loop(repo, roadmap, phase="RUNNER", executor=executor)
    assert resolved == [("execute", *ROSTER[executor])]


@pytest.mark.parametrize("executor", sorted(profiles.IMPLEMENTER_EFFORTS))
@pytest.mark.parametrize("action", ["execute", "repair"])
def test_executor_defaults_and_shipped_policy_agree(executor, action):
    # One source (IMPLEMENTER_EFFORTS) for both paths: they cannot drift apart.
    assert (
        profiles.EXECUTOR_EFFORT_OVERRIDES[executor][action]
        == profiles.shipped_model_policy_rule(action, executor).effort
        == profiles.IMPLEMENTER_EFFORTS[executor]
    )
    assert sorted(profiles.IMPLEMENTER_EFFORTS) == sorted(ROSTER)


@pytest.mark.parametrize(("executor", "expected"), [
    ("claude", ("claude-opus-5", "high")),
    ("codex", ("gpt-6-astra", "high")),
])
def test_governed_repair_escalation_keeps_the_shipped_high_effort(executor, expected, tmp_path):
    # A governed repair that escalates to the planner class keeps main's shipped `high`
    # effort: the roster's per-executor implementer effort applies to the implementer
    # class only. Driven through the run_loop seam; the escalated policy is captured
    # and the run stops before launch.
    import subprocess
    from unittest.mock import patch

    from phase_loop_runtime import runner
    from phase_loop_runtime.events import append_event
    from phase_loop_runtime.models import LoopEvent, utc_now
    from phase_loop_runtime.provenance import event_provenance

    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "CONTRACT", roadmap, owned_files=("README.md",))
    subprocess.run(["git", "add", str(plan.relative_to(repo))], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add repair plan"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
    blocker = {
        "human_required": False,
        "blocker_class": "repeated_verification_failure",
        "blocker_summary": "Repair emitted the same malformed closeout.",
        "required_human_inputs": (),
        "access_attempts": (),
    }
    for _ in range(2):
        append_event(repo, LoopEvent(
            timestamp=utc_now(), repo=str(repo), roadmap=str(roadmap), phase="CONTRACT",
            action="run", status="blocked", model=ROSTER[executor][0], reasoning_effort=ROSTER[executor][1],
            source="fixture", blocker=blocker,
            metadata={
                "launch_request": {"executor": executor, "action": "repair", "repo": str(repo),
                                   "roadmap": str(roadmap), "phase": "CONTRACT", "plan": str(plan)},
                "terminal_summary": {"terminal_status": "blocked", "verification_status": "blocked",
                                     "next_action": "Retry repair on the heavy class.", "dirty_paths": []},
            },
            selected_executor=executor, **event_provenance(roadmap, "CONTRACT"),
        ))
    escalated = []
    real = runner.apply_model_class_escalation

    def capture(policy, **kwargs):
        application = real(policy, **kwargs)
        escalated.append((application.applied, application.policy.model, application.policy.effort))
        raise _Resolved

    with patch("phase_loop_runtime.runner.run_auth_preflight",
               return_value=type("Preflight", (), {"ok": True, "metadata": {"probes": []}})()), \
            patch("phase_loop_runtime.runner.apply_model_class_escalation", side_effect=capture), \
            pytest.raises(_Resolved):
        runner.run_loop(repo, roadmap, phase="CONTRACT", executor=executor, run_mode="governed")
    assert escalated == [(True, *expected)]
