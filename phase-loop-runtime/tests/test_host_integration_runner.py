"""JEVHOST host gaps SL-7: the runner's side of the host-neutral seam.

GAPS §3.1 row 1b: an entered launch reports its acceptance verdict to an
``AcceptanceObserver`` through the runner's one ``_report_acceptance`` helper:
- the launcher's own failure (a nonzero exit, even under a trusted closeout, or an
  unavailable, stalled or timed-out run) is ``infrastructure``;
- a zero exit whose output the runner rejects (a fail-closed verification, a closeout
  gate, a Tier 3 audit, a missing or unparseable closeout, an empty host log) is
  ``quality``;
- a phase that reaches success is ``passed``;
- a reduction blocker, a child-reported blocker and host-side failures report nothing.

A raising observer is logged once and never changes the reconciled phase state.

GAPS §3.5 row 5a: the three request sites (main, delegated and lane) build through
``build_host_request``, so an integration that replaces an override is refused before the
builder or the launcher runs.

Every case enters the real ``run_loop`` (or the delegated and lane constructors) with a
host-neutral fake integration. Nothing here imports the JEV Drill adapter. Seam names are
imported test-locally behind the GAPS §3.0 availability assertion.
"""
import importlib
import re
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime import runner
from phase_loop_runtime.events import read_events
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
HOOK_FAILED = "jevdrill_acceptance_hook_failed"


def _seam(*names):
    """GAPS §3.0: import the seam test-locally and name any missing interface."""
    try:
        module = importlib.import_module("phase_loop_runtime.host_integration")
    except ImportError:
        module = None
    missing = [name for name in names if not hasattr(module, name)]
    assert not missing, f"host_integration is unavailable: missing interface {', '.join(missing)}"
    return module


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


def _result(spec, *, returncode=0, output="", **fields):
    return LaunchResult(command=spec.command, returncode=returncode, output=output, executor=spec.executor, **fields)


# --- per-case launcher results and setup -------------------------------------------------------


def _complete(spec, plan, _tmp):
    return _result(spec, output=_closeout("complete", plan))


def _failing_gate(monkeypatch, _tmp):
    """The produced-gates closeout gate fails on the run's own closeout."""
    from types import SimpleNamespace

    validation = SimpleNamespace(ok=False, missing_gates=("SL-0-gate",), produced_gates=(), warning=None,
                                 blocker_class="contract_bug",
                                 blocker_summary="Synthetic produced gate is missing from the closeout.",
                                 to_json=lambda: {"ok": False, "missing_gates": ["SL-0-gate"]})
    monkeypatch.setattr(runner, "validate_produced_gates", lambda *_a, **_k: validation)


def _red_verification(monkeypatch, _tmp):
    monkeypatch.setattr(runner, "_run_execute_verification", lambda **_k: {
        "ok": False, "code": "nonzero_exit", "blocker_summary": "Synthetic red suite."})


def _tier3(blocker_class, *, config_error=None):
    def setup(monkeypatch, _tmp):
        summary = {"config_error": config_error} if config_error else {"tier3_calls_made": 1}
        monkeypatch.setattr(runner, "_runner_tier3_closeout_audit", lambda **_k: {"summary": summary, "blocker": {
            "human_required": False, "blocker_class": blocker_class,
            "blocker_summary": f"Synthetic Tier 3 {blocker_class}.",
            "required_human_inputs": (), "access_attempts": ()}})
    return setup


def _baml_outage(monkeypatch, _tmp):
    summary = "closeout NOT evaluated: synthetic BAML worker outage"
    monkeypatch.setattr(runner, "_parsed_child_automation", lambda *_a, **_k: {
        "automation_status": "blocked", "automation_verification_status": "blocked",
        "automation_blocker_class": "unretryable_external_outage", "automation_blocker_summary": summary,
        "automation_human_required": "false", "automation_required_human_inputs": [],
        "automation_next_skill": "none", "automation_next_command": "none",
        "automation_parse_error": summary, "automation_parse_error_blocker_class": "unretryable_external_outage",
        "baml_worker_outage": "unavailable"})


def _child_blocker(spec, plan, _tmp):
    return _result(spec, output=build_fake_automation_output(
        status="blocked", blocker_class="repeated_verification_failure",
        blocker_summary="Synthetic child-reported blocker.", verification_status="blocked", artifact=str(plan)))


def _log_result(spec, tmp, *, write):
    log = tmp / "host-owned.log"
    if write:
        log.write_text("", encoding="utf-8")
    return _result(spec, log_path=str(log), process_pid=4242)


INFRA, QUALITY, PASSED = (False, "infrastructure"), (False, "quality"), (True, None)

# case id -> (launcher result, setup, verdict or None, literal phase status, reconciled blocker class)
CASES = {
    "nonzero_exit_is_infrastructure": (lambda spec, plan, tmp: _result(spec, returncode=1), None, INFRA, "unknown", None),
    "trusted_closeout_keeps_exit_8_as_infrastructure": (
        lambda spec, plan, tmp: _result(spec, returncode=8, output=_closeout("complete", plan)), None, INFRA,
        "complete", None),
    "unavailable_launch_is_infrastructure": (
        lambda spec, plan, tmp: _result(spec, returncode=None, available=False, output=_closeout("complete", plan)),
        None, INFRA, None, None),
    "zero_exit_failing_gate_is_quality": (_complete, _failing_gate, QUALITY, "blocked", "contract_bug"),
    "failed_verification_beats_a_complete_closeout": (_complete, _red_verification, QUALITY, None, None),
    "tier3_rejection_is_quality": (_complete, _tier3("repeated_verification_failure"), QUALITY, "blocked",
                                   "repeated_verification_failure"),
    "tier3_config_error_reports_nothing": (_complete, _tier3("contract_bug", config_error="malformed"), None,
                                           "blocked", "contract_bug"),
    "tier3_outage_reports_nothing": (_complete, _tier3("unretryable_external_outage"), None, "blocked",
                                     "unretryable_external_outage"),
    "missing_shared_closeout_is_quality": (lambda spec, plan, tmp: _result(spec, output="no closeout here\n"), None,
                                           QUALITY, "blocked", "repeated_verification_failure"),
    "invalid_closeout_status_is_quality": (
        lambda spec, plan, tmp: _result(spec, output=build_fake_automation_output(status="bogus", artifact=str(plan))),
        None, QUALITY, "blocked", None),
    "baml_outage_reports_nothing": (_complete, _baml_outage, None, "blocked", "unretryable_external_outage"),
    "success_is_passed": (_complete, None, PASSED, "complete", None),
    "child_reported_blocker_reports_nothing": (_child_blocker, None, None, "blocked",
                                               "repeated_verification_failure"),
    # Launch-contract blockers on a zero exit, each through the real finalizer.
    "contract_stalled_is_infrastructure": (lambda spec, plan, tmp: _result(spec, stalled=True), None, INFRA,
                                           "blocked", "stalled_child_observation"),
    "contract_timed_out_is_infrastructure": (lambda spec, plan, tmp: _result(spec, timed_out=True), None, INFRA,
                                             "blocked", "repeated_verification_failure"),
    "contract_interrupted_reports_nothing": (lambda spec, plan, tmp: _result(spec, interrupted=True), None, None,
                                             "blocked", "repeated_verification_failure"),
    "contract_surviving_child_reports_nothing": (
        lambda spec, plan, tmp: _result(spec, cleanup_evidence={"process_alive_after_cleanup": True}), None, None,
        "blocked", "repeated_verification_failure"),
    "contract_no_closeout_is_quality": (
        lambda spec, plan, tmp: _result(spec, codex_turn_completion={"completed": False}), None, QUALITY,
        "blocked", "contract_bug"),
    "contract_missing_host_log_reports_nothing": (lambda spec, plan, tmp: _log_result(spec, tmp, write=False), None,
                                                  None, "blocked", "repeated_verification_failure"),
    "contract_empty_host_log_is_quality": (lambda spec, plan, tmp: _log_result(spec, tmp, write=True), None, QUALITY,
                                           "blocked", "repeated_verification_failure"),
}


def _run_case(tmp_path, monkeypatch, case, *, raises=False):
    make, setup, _verdict, _status, _blocker = CASES[case]
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo, roadmap, plan = _phase(tmp_path, monkeypatch)
    if setup is not None:
        setup(monkeypatch, tmp_path)
    executed = []

    def launcher(spec, **_kwargs):
        executed.append(spec)
        return make(spec, plan, tmp_path)

    monkeypatch.setattr(runner, "launch_with_spec", launcher)
    observer = Observer(raises=raises)
    snapshot, _results = runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex", closeout_mode="commit",
                                         jevdrill_adapter=observer)
    assert observer.prepared == ["main"]
    assert len(observer.launched) == len(executed) == 1, "the launch was not entered"
    return repo, roadmap, snapshot, observer


@pytest.mark.parametrize("case", list(CASES))
def test_acceptance_verdicts_reach_the_observer(tmp_path, monkeypatch, case):
    _make, _setup, verdict, status, blocker_class = CASES[case]
    repo, roadmap, snapshot, observer = _run_case(tmp_path, monkeypatch, case)
    expected = [] if verdict is None else [(RUN_ID, *verdict)]
    assert observer.verdicts == expected
    reconciled = reconcile(repo, roadmap)
    if status is not None:
        assert snapshot.phases["RUNNER"] == status
        assert reconciled.phases["RUNNER"] == status
    if blocker_class is not None:
        assert reconciled.blocker_class == blocker_class
        assert reconciled.blocker_summary
    if case == "failed_verification_beats_a_complete_closeout":
        transitions = [event["metadata"]["state_transition"].get("reason") for event in read_events(repo)
                       if event["action"] == "state_transition"]
        assert "runner_verification_failed" in transitions
    assert not [event for event in read_events(repo) if event["action"] == HOOK_FAILED]


def test_launch_contract_verdict_uses_the_reason_captured_at_the_check(tmp_path, monkeypatch):
    """GAPS §3.1: the verdict follows the blocker actually selected, not a later re-check.

    The missing-log blocker is selected; the log then appears before verdict selection. The
    run must still report nothing, as a missing host-owned log does.
    """
    import inspect

    assert "reason_out" in inspect.signature(runner._launch_contract_blocker).parameters, (
        "runner does not capture the blocker reason")
    check = runner._launch_contract_blocker

    def racing_check(result, *args, **kwargs):
        selected = check(result, *args, **kwargs)
        if result.log_path:
            open(result.log_path, "w", encoding="utf-8").close()
        return selected

    monkeypatch.setattr(runner, "_launch_contract_blocker", racing_check)
    repo, roadmap, snapshot, observer = _run_case(tmp_path, monkeypatch, "contract_missing_host_log_reports_nothing")
    assert observer.verdicts == []
    assert snapshot.phases["RUNNER"] == "blocked"
    assert "durable output log" in reconcile(repo, roadmap).blocker_summary


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


def _reconciled_state(repo, roadmap):
    state = reconcile(repo, roadmap)
    terminal = state.terminal_summary or {}
    closeout = state.closeout_summary or {}
    return {
        "phases": state.phases,
        "human_required": state.human_required,
        "blocker_class": state.blocker_class,
        "blocker_summary": state.blocker_summary,
        "terminal_status": terminal.get("terminal_status"),
        "verification_status": terminal.get("verification_status"),
        "closeout_terminal_status": state.closeout_terminal_status,
        "closeout_status": closeout.get("status"),
    }


@pytest.mark.parametrize("case", ["zero_exit_failing_gate_is_quality", "nonzero_exit_is_infrastructure",
                                  "success_is_passed"])
def test_a_raising_observer_leaves_the_reconciled_state_and_logs_one_event(tmp_path, monkeypatch, case):
    base_repo, base_roadmap, base, quiet = _run_case(tmp_path / "quiet", monkeypatch, case)
    repo, roadmap, snapshot, loud = _run_case(tmp_path / "loud", monkeypatch, case, raises=True)
    verdict = CASES[case][2]
    assert quiet.verdicts == loud.verdicts == [(RUN_ID, *verdict)]
    assert snapshot.phases == base.phases
    assert snapshot.phases["RUNNER"] == CASES[case][3]
    assert _reconciled_state(repo, roadmap) == _reconciled_state(base_repo, base_roadmap)
    if CASES[case][4] is not None:
        assert _reconciled_state(repo, roadmap)["blocker_class"] == CASES[case][4]
    failures = [event for event in read_events(repo) if event["action"] == HOOK_FAILED]
    assert len(failures) == 1
    _assert_metadata_only(failures[0], verdict[1] or "passed")
    assert not [event for event in read_events(base_repo) if event["action"] == HOOK_FAILED]


def _assert_metadata_only(diagnostic, verdict):
    """The diagnostic carries the failure record and no phase state."""
    assert diagnostic["metadata"] == {HOOK_FAILED: {
        "execution_run_id": RUN_ID, "verdict": verdict, "error_type": "RuntimeError"}}
    for field in ("status", "blocker", "terminal_summary", "closeout_summary", "selected_executor"):
        assert field not in diagnostic, field


NEWER_CLOSEOUT_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_a_raising_observer_never_rolls_back_a_newer_ledger_event(tmp_path, monkeypatch):
    """Another writer appends a newer ``complete`` between the observer failing and the
    diagnostic landing. The newer status, blocker and closeout state must survive."""
    from phase_loop_runtime.models import LoopEvent
    from phase_loop_runtime.provenance import event_provenance

    newer = []

    def other_writer(repo, roadmap):
        from phase_loop_runtime.events import append_event

        append_event(repo, LoopEvent(
            timestamp="2999-01-01T00:00:00Z", repo=str(repo), roadmap=str(roadmap), phase="RUNNER",
            action="run", status="complete", model="m", reasoning_effort="high", source="user_override",
            metadata={"closeout": {"closeout_mode": "commit", "closeout_action": "commit",
                                   "closeout_commit": NEWER_CLOSEOUT_COMMIT}},
            **event_provenance(Path(roadmap), "RUNNER")))
        newer.append(True)

    def interleave(write):
        def wrapped(repo, item, *args, **kwargs):
            action = item.get("action") if isinstance(item, dict) else getattr(item, "action", None)
            if action == HOOK_FAILED and not newer:
                roadmap = item.get("roadmap") if isinstance(item, dict) else item.roadmap
                other_writer(repo, roadmap)
            return write(repo, item, *args, **kwargs)
        return wrapped

    monkeypatch.setattr(runner, "append_payload", interleave(runner.append_payload))
    monkeypatch.setattr(runner, "append_event", interleave(runner.append_event))
    repo, roadmap, snapshot, loud = _run_case(tmp_path, monkeypatch, "zero_exit_failing_gate_is_quality", raises=True)
    assert loud.verdicts == [(RUN_ID, False, "quality")]
    assert newer == [True], "the interleaved writer did not run"
    events = read_events(repo)
    assert [event["action"] for event in events][-2:] == ["run", HOOK_FAILED]
    state = reconcile(repo, roadmap)
    assert state.phases["RUNNER"] == "complete", "the diagnostic rolled back the newer event"
    assert state.blocker_class is None and state.blocker_summary is None and not state.human_required
    assert (state.closeout_summary or {}).get("closeout_commit") == NEWER_CLOSEOUT_COMMIT
    _assert_metadata_only(events[-1], "quality")


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


def _enter(entrypoint, repo, roadmap, plan, integration=None, **main_kwargs):
    if entrypoint == "main":
        runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex", dry_run=True,
                        jevdrill_adapter=integration, **main_kwargs)
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


def _observe_builder_and_launcher(monkeypatch):
    built, launched = [], []
    builder = runner.build_launch_request
    monkeypatch.setattr(runner, "build_launch_request", lambda **kwargs: built.append(kwargs) or builder(**kwargs))
    monkeypatch.setattr(runner, "launch_with_spec", lambda spec, **_k: launched.append(spec) or LaunchResult(
        command=spec.command, returncode=0, output="", executor=spec.executor, dry_run=True))
    return built, launched


@pytest.mark.parametrize("entrypoint", ["main", "delegated", "lane"])
def test_runner_refuses_an_integration_that_replaces_an_override(tmp_path, monkeypatch, entrypoint):
    seam = _seam("HostOverrideViolation", "build_host_request")
    repo, roadmap, plan = _phase(tmp_path, monkeypatch)
    built, launched = _observe_builder_and_launcher(monkeypatch)
    if entrypoint != "main":
        # The delegated and lane constructors resolve the executor default profile; pin it
        # as an operator override so only the guard decides.
        resolve = runner.resolve_profile_for_executor
        monkeypatch.setattr(runner, "resolve_profile_for_executor",
                            lambda **kwargs: replace(resolve(**kwargs), source="user_override"))
    integration = Replacer()
    refused = None
    try:
        _enter(entrypoint, repo, roadmap, plan, integration, model="gpt-5.4", effort="high")
    except seam.HostOverrideViolation as exc:
        refused = exc
    assert [mode for mode, _selection in integration.prepared] == [entrypoint]
    assert integration.prepared[0][1].source not in ("default", "codex_default")
    assert launched == [] and integration.launched == [], "the launcher was called"
    assert built == [], "the builder was called"
    assert isinstance(refused, seam.HostOverrideViolation)


@pytest.mark.parametrize("entrypoint", ["main", "delegated", "lane"])
def test_request_sites_without_an_integration_build_exactly_once(tmp_path, monkeypatch, entrypoint):
    """Control: with no integration the three request sites are unchanged."""
    repo, roadmap, plan = _phase(tmp_path, monkeypatch)
    built, launched = _observe_builder_and_launcher(monkeypatch)
    _enter(entrypoint, repo, roadmap, plan)
    assert len(built) == 1 and len(launched) == 1
