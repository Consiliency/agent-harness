"""JEVHOST host gaps SL-7: the runner's side of the host-neutral seam.

GAPS §3.1 row 1b: an entered launch reports its acceptance verdict to an
``AcceptanceObserver`` through the runner's one ``_report_acceptance`` helper. A nonzero
exit is ``infrastructure``, a zero exit that a post-launch gate or verification blocks is
``quality``, a phase that reaches success is ``passed``, and a reduction blocker or any
unrelated blocker reports nothing. A raising observer is logged once and never changes
the phase classification.

GAPS §3.5 row 5a: the three request sites (main, delegated and lane) build through
``build_host_request``, so an integration that replaces an override is refused before the
builder or the launcher runs.

Every integration here is a host-neutral fake. Nothing here imports the JEV Drill adapter.
"""
import re
from dataclasses import replace

import pytest

from phase_loop_runtime import runner
from phase_loop_runtime.events import read_events
from phase_loop_runtime.host_integration import HostOverrideViolation
from phase_loop_runtime.launcher import LaunchResult
from phase_loop_runtime.models import (
    DelegationBudget,
    DelegationRequest,
    HarnessLaneAssignment,
    PromptBundle,
)
from phase_loop_runtime.reconcile import reconcile
from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, make_repo, write_phase_plan

RUN_ID = "synthetic-execution-run-0001"


class Observer:
    """A pass-through integration that observes acceptance verdicts."""

    def __init__(self, *, raises=False):
        self.raises = raises
        self.prepared, self.launched, self.verdicts = [], [], []

    def prepare(self, *, mode, dry_run, **kwargs):
        self.prepared.append(mode)
        return kwargs

    def launch(self, launch, spec, **kwargs):
        self.launched.append(spec)
        return replace(launch(spec, **kwargs), jevdrill_execution_run={"execution_run_id": RUN_ID})

    def record_acceptance_outcome(self, execution_run_id, *, passed, failure_class):
        self.verdicts.append((execution_run_id, passed, failure_class))
        if self.raises:
            raise RuntimeError("synthetic observer outage")


def _phase(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "RUNNER", roadmap, owned_files=("notes.md",))
    commit_fixture_paths(repo, "fixture", plan)
    monkeypatch.setattr(runner, "build_prompt", lambda *_a, **_k: PromptBundle("synthetic-workflow", "fixture", "inline"))
    monkeypatch.setattr(runner, "run_auth_preflight", lambda *_a, **_k: None)
    return repo, roadmap, plan


def _closeout(status, plan):
    return build_fake_automation_output(status=status, verification_status="passed", artifact=str(plan),
                                        artifact_state="tracked")


def _failing_gate(monkeypatch):
    """The produced-gates closeout gate fails on the run's own closeout."""
    from types import SimpleNamespace

    validation = SimpleNamespace(ok=False, missing_gates=("SL-0-gate",), produced_gates=(), warning=None,
                                 blocker_class="contract_bug",
                                 blocker_summary="Synthetic produced gate is missing from the closeout.",
                                 to_json=lambda: {"ok": False, "missing_gates": ["SL-0-gate"]})
    monkeypatch.setattr(runner, "validate_produced_gates", lambda *_a, **_k: validation)


def _child_blocker(plan):
    return build_fake_automation_output(status="blocked", blocker_class="repeated_verification_failure",
                                        blocker_summary="Synthetic child-reported blocker.",
                                        verification_status="blocked", artifact=str(plan))


# case id -> (returncode, output builder, extra setup, expected verdict or None)
CASES = {
    "nonzero_exit_is_infrastructure": (1, lambda plan: "", None, (False, "infrastructure")),
    "zero_exit_failing_gate_is_quality": (0, lambda plan: _closeout("complete", plan), _failing_gate,
                                          (False, "quality")),
    "success_is_passed": (0, lambda plan: _closeout("complete", plan), None, (True, None)),
    "unrelated_child_blocker_reports_nothing": (0, _child_blocker, None, None),
}


def _run_case(tmp_path, monkeypatch, case, *, raises=False):
    returncode, output, setup, _expected = CASES[case]
    repo, roadmap, plan = _phase(tmp_path, monkeypatch)
    if setup is not None:
        setup(monkeypatch)
    executed = []

    def launcher(spec, **_kwargs):
        executed.append(spec)
        return LaunchResult(command=spec.command, returncode=returncode, output=output(plan), executor=spec.executor)

    monkeypatch.setattr(runner, "launch_with_spec", launcher)
    observer = Observer(raises=raises)
    snapshot, _results = runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex", closeout_mode="commit",
                                         jevdrill_adapter=observer)
    assert observer.prepared == ["main"]
    assert len(observer.launched) == len(executed) == 1, "the launch was not entered"
    return repo, roadmap, snapshot, observer


@pytest.mark.parametrize("case", list(CASES))
def test_acceptance_verdicts_reach_the_observer(tmp_path, monkeypatch, case):
    _repo, _roadmap, snapshot, observer = _run_case(tmp_path, monkeypatch, case)
    expected = CASES[case][3]
    if expected is None:
        assert observer.verdicts == []
        assert snapshot.phases["RUNNER"] == "blocked"
    else:
        passed, failure_class = expected
        assert observer.verdicts == [(RUN_ID, passed, failure_class)]
        assert snapshot.phases["RUNNER"] == ("complete" if passed else observer_status(snapshot))


def observer_status(snapshot):
    status = snapshot.phases["RUNNER"]
    assert status in {"blocked", "unknown"}
    return status


def test_acceptance_verdicts_reach_the_observer_reduction_blocker_reports_nothing(monkeypatch):
    """A reduction blocker is not judged on the run (GAPS §3.1), so it reports no verdict.

    With an integration the runner refuses concurrent dispatch (``run_loop``'s serial
    guard), and concurrent dispatch is the only path that produces a reduction blocker.
    So this drives the SCHED trusted transfer-conflict anchor, whose middle phases are
    entered and then reduction-blocked, and records every verdict the runner hands to
    ``_deliver_acceptance``. The blocked phases hand none. A phase that completes in the
    same run hands ``passed``, which shows the recorder is live.
    """
    from test_phase_loop_v45_schedharden import MIDDLE_DIRTY, V45SchedHardenRealExecTest

    assert hasattr(runner, "_deliver_acceptance"), "runner has no acceptance delivery helper"
    handed = []
    deliver = runner._deliver_acceptance

    def recorder(integration, result, verdict):
        match = re.search(r"phase-plan-v1-([A-Z_]+)\.md", result.output or "")
        handed.append((match.group(1) if match else None, verdict))
        return deliver(integration, result, verdict)

    monkeypatch.setattr(runner, "_deliver_acceptance", recorder)
    case = V45SchedHardenRealExecTest()
    case.setUp()
    try:
        case._assert_trusted_transfer_conflict_blocks_reduction_and_preserves_generation()
    finally:
        case.doCleanups()
    phases = {phase for phase, _verdict in handed}
    assert not phases & set(MIDDLE_DIRTY), handed
    assert ("FOUND", "passed") in handed, handed


def test_a_raising_observer_leaves_the_classification_and_logs_one_event(tmp_path, monkeypatch):
    base_repo, base_roadmap, base, quiet = _run_case(tmp_path / "quiet", monkeypatch, "nonzero_exit_is_infrastructure")
    repo, roadmap, snapshot, loud = _run_case(tmp_path / "loud", monkeypatch, "nonzero_exit_is_infrastructure",
                                              raises=True)
    assert quiet.verdicts == loud.verdicts == [(RUN_ID, False, "infrastructure")]
    assert snapshot.phases == base.phases
    assert reconcile(repo, roadmap).phases == reconcile(base_repo, base_roadmap).phases
    failures = [event for event in read_events(repo) if event["action"] == "jevdrill_acceptance_hook_failed"]
    assert len(failures) == 1
    assert failures[0]["status"] == snapshot.phases["RUNNER"]
    assert failures[0]["metadata"]["jevdrill_acceptance_hook_failed"] == {
        "execution_run_id": RUN_ID, "verdict": "infrastructure", "error_type": "RuntimeError"}
    assert not [event for event in read_events(base_repo) if event["action"] == "jevdrill_acceptance_hook_failed"]


@pytest.mark.parametrize("contract", ["stalled", "timed_out", "interrupted", "contract_bug", "zero_byte_log",
                                      "missing_log", "cleanup_left_child"])
def test_launch_contract_blocker_verdict_records_whether_the_run_was_judged(tmp_path, contract):
    log = tmp_path / "child.log"
    fields = {"stalled": {"stalled": True}, "timed_out": {"timed_out": True}, "interrupted": {"interrupted": True},
              "cleanup_left_child": {"cleanup_evidence": {"process_alive_after_cleanup": True}}}.get(contract, {})
    if contract == "zero_byte_log":
        log.write_text("", encoding="utf-8")
    result = LaunchResult(command=["codex"], returncode=0, output="", executor="codex",
                          log_path=str(log) if contract in {"zero_byte_log", "missing_log"} else None, **fields)
    blocker = {"blocker_class": "contract_bug" if contract == "contract_bug" else "repeated_verification_failure"}
    expected = {"stalled": "infrastructure", "timed_out": "infrastructure", "contract_bug": "quality",
                "zero_byte_log": "quality"}.get(contract)
    assert runner._launch_contract_acceptance_verdict(result, blocker) == expected


# --- GAPS §3.5 row 5a ------------------------------------------------------------------------


class Replacer:
    """A host-neutral integration that replaces the operator's model and keeps the source."""

    def __init__(self):
        self.prepared, self.launched = [], []

    def prepare(self, *, mode, dry_run, **kwargs):
        self.prepared.append((mode, kwargs["model_selection"]))
        selection = kwargs["model_selection"]
        return {**kwargs, "model_selection": replace(selection, model=f"{selection.model}-replaced")}

    def launch(self, launch, spec, **kwargs):
        self.launched.append(spec)
        return launch(spec, **kwargs)


@pytest.mark.parametrize("entrypoint", ["main", "delegated", "lane"])
def test_runner_refuses_an_integration_that_replaces_an_override(tmp_path, monkeypatch, entrypoint):
    repo, roadmap, plan = _phase(tmp_path, monkeypatch)
    built, launched = [], []
    builder = runner.build_launch_request

    def observed_builder(**kwargs):
        built.append(kwargs)
        return builder(**kwargs)

    def observed_launcher(spec, **_kwargs):
        launched.append(spec)
        return LaunchResult(command=spec.command, returncode=0, output="", executor=spec.executor, dry_run=True)

    monkeypatch.setattr(runner, "build_launch_request", observed_builder)
    monkeypatch.setattr(runner, "launch_with_spec", observed_launcher)
    if entrypoint != "main":
        # The delegated and lane constructors resolve the executor default profile; pin it
        # as an operator override so only the guard decides.
        resolve = runner.resolve_profile_for_executor
        monkeypatch.setattr(runner, "resolve_profile_for_executor",
                            lambda **kwargs: replace(resolve(**kwargs), source="user_override"))
    integration = Replacer()
    refused = None
    try:
        if entrypoint == "main":
            runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex", model="gpt-5.4", effort="high",
                            dry_run=True, jevdrill_adapter=integration)
        elif entrypoint == "delegated":
            runner.launch_delegated_child(
                repo=repo, roadmap=roadmap, parent_phase="RUNNER", parent_action="execute", plan=plan,
                request=DelegationRequest(request_id="synthetic", product_action="review", target_executor="codex",
                                          reason="synthetic conformance", owned_files=("notes.md",),
                                          expected_output="findings", budget=DelegationBudget(max_seconds=60)),
                dry_run=True, jevdrill_adapter=integration)
        else:
            runner.launch_harness_lane_work_unit(
                repo=repo, roadmap=roadmap, plan=plan,
                assignment=HarnessLaneAssignment(phase="RUNNER", lane_id="SL-0", work_unit_kind="lane_execute",
                                                 owned_files=("notes.md",)),
                dry_run=True, jevdrill_adapter=integration)
    except HostOverrideViolation as exc:
        refused = exc
    assert [mode for mode, _selection in integration.prepared] == [entrypoint]
    assert integration.prepared[0][1].source not in ("default", "codex_default")
    assert launched == [] and integration.launched == [], "the launcher was called"
    assert built == [], "the builder was called"
    assert isinstance(refused, HostOverrideViolation)


@pytest.mark.parametrize("entrypoint", ["main", "delegated", "lane"])
def test_request_sites_without_an_integration_build_exactly_once(tmp_path, monkeypatch, entrypoint):
    """With no integration the three request sites are unchanged: one build, one launch."""
    repo, roadmap, plan = _phase(tmp_path, monkeypatch)
    built, launched = [], []
    builder = runner.build_launch_request
    monkeypatch.setattr(runner, "build_launch_request", lambda **kwargs: built.append(kwargs) or builder(**kwargs))
    monkeypatch.setattr(runner, "launch_with_spec", lambda spec, **_k: launched.append(spec) or LaunchResult(
        command=spec.command, returncode=0, output="", executor=spec.executor, dry_run=True))
    if entrypoint == "main":
        runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex", dry_run=True)
    elif entrypoint == "delegated":
        runner.launch_delegated_child(
            repo=repo, roadmap=roadmap, parent_phase="RUNNER", parent_action="execute", plan=plan,
            request=DelegationRequest(request_id="synthetic", product_action="review", target_executor="codex",
                                      reason="synthetic conformance", owned_files=("notes.md",),
                                      expected_output="findings", budget=DelegationBudget(max_seconds=60)),
            dry_run=True)
    else:
        runner.launch_harness_lane_work_unit(
            repo=repo, roadmap=roadmap, plan=plan,
            assignment=HarnessLaneAssignment(phase="RUNNER", lane_id="SL-0", work_unit_kind="lane_execute",
                                             owned_files=("notes.md",)),
            dry_run=True)
    assert len(built) == 1 and len(launched) == 1
