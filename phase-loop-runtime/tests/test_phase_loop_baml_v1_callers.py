"""Caller handling of BAML worker faults and the request cap (agent-harness#1135).

The plan's caller table (#22, #24, #27): every call site that can reach the
BAML worker maps a ``BamlWorkerError`` to "not evaluated" or propagates it
typed, and never turns it into a content verdict or a skip.

Worker faults here are REAL: the bridge function is made to sleep inside the
real v1 runtime and the worker is SIGKILLed mid-call, with retries forced to
0.  Request-cap failures are real cap checks (``_REQUEST_CAP`` lowered through
the module constant where a 4 MiB fixture would be absurd).  The executor
launch itself is the usual test seam (``launch_with_spec``).
"""
from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from phase_loop_runtime import baml_modular as m
from phase_loop_runtime import discovery, evidence_audit, runner
from phase_loop_runtime.baml_modular import BamlValidationError, BamlWorkerError
from phase_loop_runtime.launcher import AuthPreflightResult, LaunchResult
from phase_loop_test_utils import build_fake_delegation_request, commit_fixture_paths, make_repo, write_phase_plan
from test_phase_loop_baml_v1_runtime import OK, OK_PAYLOAD, _hostile, _Killer, _raises, _sleep, _use

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent / "src" / "phase_loop_runtime"
CALL_SITES = TESTS / "data" / "baml_call_sites.json"
HANDLER_ALLOWLIST = TESTS / "data" / "baml_worker_handler_allowlist.json"
REACHING = {
    "parse_baml_response", "build_baml_request", "parse_closeout_payload_doc", "parse_closeout_payload",
    "evaluate_suspected_fake_evidence", "build_prompt", "build_prompt_bundle", "build_lane_prompt_bundle",
    "launch_delegated_child", "_parsed_child_automation",
}

pytestmark = pytest.mark.skipif(os.name != "posix", reason="real mid-call SIGKILL of the worker")


@pytest.fixture(autouse=True)
def _fresh_client():
    _use(None)
    yield
    _use(None)
    m._reset_worker_for_tests()


@contextmanager
def _worker_fault(bridge_fn: str):
    """Every call of ``bridge_fn`` hangs in the real runtime and is SIGKILLed."""
    _use(_hostile(bridge_fn, _sleep(30)), retries=0)
    killer = _Killer(every=True, delay=0.2)
    try:
        yield killer
    finally:
        killer.close()


@contextmanager
def _lowered_cap(cap: int):
    real = m._REQUEST_CAP
    m._REQUEST_CAP = cap
    try:
        yield
    finally:
        m._REQUEST_CAP = real


def _native_closeout(**overrides) -> str:
    return json.dumps({**OK_PAYLOAD, "produced_if_gates": ["IF-0-EXTRACT-1"], **overrides})


def _repo(td: str, phases=("EXTRACT",)) -> tuple[Path, Path, dict]:
    repo = make_repo(Path(td))
    roadmap = repo / "specs" / "phase-plans-v1.md"
    roadmap.write_text(
        "# Roadmap\n\n"
        + "".join(f"### Phase {i + 1} - {p.title()} ({p})\n**Depends on**\n- (none)\n\n" for i, p in enumerate(phases)),
        encoding="utf-8",
    )
    plans = {p: write_phase_plan(repo, p, roadmap, owned_files=(f"src/{p.lower()}.py",)) for p in phases}
    commit_fixture_paths(repo, "fixture", roadmap, *plans.values())
    return repo, roadmap, plans


def _launch_returning(output: str, launched: list):
    def launch(spec, **_kwargs):
        launched.append(spec)
        return LaunchResult(command=spec.command, returncode=0, output=output, executor=spec.executor)

    return launch


@contextmanager
def _runner_seams(launch):
    with (
        patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})),
        patch("phase_loop_runtime.runner.launch_with_spec", side_effect=launch),
        patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=launch),
        patch("phase_loop_runtime.injection._resolve_pack_skill_dirs", return_value={}),
    ):
        yield


# ---------------------------------------------------------------------------
# closeout parse (#24)
# ---------------------------------------------------------------------------


def test_discovery_closeout_parse_raises_the_worker_error():
    with _worker_fault("phase_loop_parse_closeout"):
        exc = _raises(discovery.parse_closeout_payload_doc, OK, kind="native_closeout")
    assert type(exc) is BamlWorkerError and exc.kind == "died"


def test_native_closeout_status_is_not_evaluated_never_contract_bug():
    with _worker_fault("phase_loop_parse_closeout"):
        parsed = runner._parse_native_closeout_status(OK)
    assert parsed["automation_status"] == "blocked"
    assert parsed["automation_blocker_class"] == "unretryable_external_outage"
    assert parsed["automation_parse_error_blocker_class"] == "unretryable_external_outage"
    assert parsed["automation_human_required"] == "false"


def test_native_closeout_over_the_cap_keeps_the_contract_bug_mapping():
    """#27: an absurd extracted closeout object is a content problem."""
    big = _native_closeout(dirty_paths=["x" * 2048] * 8)
    with _lowered_cap(4096):
        parsed = runner._parse_native_closeout_status(big)
    assert parsed["automation_parse_error_blocker_class"] == "contract_bug"


def test_serial_finalize_persists_blocked_unretryable():
    """Downstream through _parsed_child_automation: no fallback upgrades it."""
    with tempfile.TemporaryDirectory() as td:
        repo, roadmap, plans = _repo(td)
        launched: list = []
        state = {}

        def launch(spec, **kwargs):
            launched.append(spec)
            # The prompt is built; only now does the closeout parse start failing.
            state["fault"] = _worker_fault("phase_loop_parse_closeout")
            state["fault"].__enter__()
            return LaunchResult(command=spec.command, returncode=0, output=_native_closeout(), executor=spec.executor)

        try:
            with _runner_seams(launch):
                snapshot, _results = runner.run_loop(repo, roadmap, phase="EXTRACT", executor="codex")
        finally:
            if "fault" in state:
                state["fault"].__exit__(None, None, None)
    assert len(launched) == 1
    assert snapshot.phases["EXTRACT"] == "blocked"
    assert snapshot.blocker_class == "unretryable_external_outage"


def test_wave_finalize_persists_blocked_unretryable():
    with tempfile.TemporaryDirectory() as td:
        repo, roadmap, plans = _repo(td, ("EXTRACT", "IMPORT"))
        state = {"launched": []}

        def launch(spec, **kwargs):
            state["launched"].append(spec)
            if len(state["launched"]) == 2:
                state["fault"] = _worker_fault("phase_loop_parse_closeout")
                state["fault"].__enter__()
            phase = "EXTRACT" if "EXTRACT" in spec.prompt_bundle.render_prompt() else "IMPORT"
            output = _native_closeout(produced_if_gates=[f"IF-0-{phase}-1"])
            return LaunchResult(command=spec.command, returncode=0, output=output, executor=spec.executor)

        try:
            with _runner_seams(launch), patch("phase_loop_runtime.worker_pool.os.cpu_count", return_value=4):
                snapshot, _results = runner.run_loop(repo, roadmap, phase_scheduler_mode="concurrent", max_phases=2)
        finally:
            if "fault" in state:
                state["fault"].__exit__(None, None, None)
    assert len(state["launched"]) == 2
    for phase in ("EXTRACT", "IMPORT"):
        assert snapshot.phases[phase] == "blocked", (phase, snapshot.phases)


# ---------------------------------------------------------------------------
# Tier 3 (#24, #27)
# ---------------------------------------------------------------------------


def _tier3_repo(td: str) -> Path:
    repo = Path(td)
    (repo / "evidence.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")
    return repo


def test_tier3_worker_fault_blocks_the_closeout_never_uncertain():
    with tempfile.TemporaryDirectory() as td, _worker_fault("phase_loop_evidence_request"):
        audit = evidence_audit.run_tier3_runner_audit(_tier3_repo(td), tier3_budget=1, dirty_only=False)
    assert audit.blocker is not None
    assert audit.blocker["blocker_class"] == "unretryable_external_outage"
    assert audit.blocker["human_required"] is False
    assert audit.warnings == () and audit.invocations == ()


def test_tier3_over_cap_sample_takes_the_v0_uncertain_path():
    finding = evidence_audit.LooseUniformFinding(
        json_artifact="evidence.json", json_pointer="$.scores", array_length=4, mean=1.0, stdev=0.0, coefficient_of_variation=0.0
    )
    with tempfile.TemporaryDirectory() as td:
        sample = Path(td) / "evidence.json"
        sample.write_text("x" * 20000, encoding="utf-8")
        with _lowered_cap(8192):
            judgment = evidence_audit.evaluate_suspected_fake_evidence(finding, sample, "expected", max_sample_bytes=16384)
    assert judgment.verdict == "uncertain"


def test_tier3_cli_path_propagates_the_worker_error():
    with tempfile.TemporaryDirectory() as td, _worker_fault("phase_loop_evidence_request"):
        exc = _raises(evidence_audit.run_evidence_audit, _tier3_repo(td), tier2_enabled=True, enable_tier_3=True, dirty_only=False)
    assert type(exc) is BamlWorkerError


# ---------------------------------------------------------------------------
# launch prompt (#22, #27)
# ---------------------------------------------------------------------------


def test_serial_prompt_build_fault_propagates_and_launches_nothing():
    with tempfile.TemporaryDirectory() as td:
        repo, roadmap, _plans = _repo(td)
        launched: list = []
        with _runner_seams(_launch_returning(_native_closeout(), launched)), _worker_fault("phase_loop_closeout_request"):
            exc = _raises(runner.run_loop, repo, roadmap, phase="EXTRACT", executor="codex")
    assert type(exc) is BamlWorkerError
    assert launched == []


def test_serial_prompt_over_the_cap_propagates_plain_and_launches_nothing():
    with tempfile.TemporaryDirectory() as td:
        repo, roadmap, _plans = _repo(td)
        launched: list = []
        with _runner_seams(_launch_returning(_native_closeout(), launched)), _lowered_cap(64):
            exc = _raises(runner.run_loop, repo, roadmap, phase="EXTRACT", executor="codex")
    assert type(exc) is BamlValidationError
    assert launched == []


@pytest.mark.parametrize("failure", ["worker", "cap"])
def test_wave_prepare_failure_propagates_before_the_pool(failure):
    """Only the freshly created, unlaunched worktrees are reclaimed; a
    previously preserved generation's branch and worktree survive."""
    with tempfile.TemporaryDirectory() as td:
        repo, roadmap, _plans = _repo(td, ("EXTRACT", "IMPORT"))
        preserved = runner.create_phase_worktree(
            repo, phase="EARLIER", target_branch=runner.current_branch(repo), base_sha=runner.resolve_base_sha(repo),
            workspace_mount=Path(td) / "worktrees",
        )
        created: list = []
        real_create = runner.create_phase_worktree

        def observe_create(*args, **kwargs):
            handle = real_create(*args, workspace_mount=Path(td) / "worktrees", **kwargs)
            created.append(handle)
            return handle

        pool_calls: list = []
        launched: list = []
        fault = _worker_fault("phase_loop_closeout_request") if failure == "worker" else _lowered_cap(64)
        with (
            _runner_seams(_launch_returning(_native_closeout(), launched)),
            patch("phase_loop_runtime.runner.create_phase_worktree", side_effect=observe_create),
            patch("phase_loop_runtime.runner.run_phase_worker_pool", side_effect=lambda *a, **k: pool_calls.append(1)),
            fault,
        ):
            exc = _raises(runner.run_loop, repo, roadmap, phase_scheduler_mode="concurrent", max_phases=2)
        assert type(exc) is (BamlWorkerError if failure == "worker" else BamlValidationError)
        assert pool_calls == [] and launched == []
        assert created, "the wave never reached prepare"
        for handle in created:
            assert not Path(handle.worktree_path).exists(), handle.worktree_path
        assert Path(preserved.worktree_path).exists()
        branches = subprocess.run(
            ["git", "-C", str(repo), "branch", "--list", preserved.temp_branch], capture_output=True, text=True, check=True
        ).stdout
        assert preserved.temp_branch in branches


def _owned_plan(repo: Path, roadmap: Path) -> Path:
    body = (
        "# RUNNER\n\n## Lanes\n\n### SL-0 - RUNNER\n- **Owned files**: `notes.md`\n\n"
        "**Produces**: IF-0-TEST-1\n\n## Acceptance Criteria\n"
        "- [ ] compatibility fixture — proven by test, falsified by fails if test fails\n\n"
        "## Verification\n" f"- `{sys.executable} -c \"print('verify')\"`\n"
    )
    plan = write_phase_plan(repo, "RUNNER", roadmap, body=body)
    commit_fixture_paths(repo, "add plan", roadmap, plan)
    return plan


def _run_delegated(td: str, *, arm_after_parent_launch, child_output: str | None = None):
    repo = make_repo(Path(td))
    roadmap = repo / "specs" / "phase-plans-v1.md"
    roadmap.write_text("# Roadmap\n\n### Phase 0 - Runner (RUNNER)\n", encoding="utf-8")
    _owned_plan(repo, roadmap)
    request = build_fake_delegation_request(
        request_id="req-1", target_executor="codex", product_action="execute", owned_files=("notes.md",),
        expected_output="Delegated child work",
    )
    launches: list = []
    parsed_calls: list = []
    real_parsed = runner._parsed_child_automation
    state = {}

    def parsed(result, spec):
        parsed_calls.append(spec)
        if spec is launches[0]:  # the parent asks for a delegation
            return {"automation_status": "delegated", "delegation_request": request}
        state["child"] = real_parsed(result, spec)
        return state["child"]

    def launch(spec, **kwargs):
        launches.append(spec)
        if len(launches) == 1:
            state["armed"] = arm_after_parent_launch()
            state["armed"].__enter__()
            return LaunchResult(command=spec.command, returncode=0, output="", executor=spec.executor)
        return LaunchResult(command=spec.command, returncode=0, output=child_output or _native_closeout(), executor=spec.executor)

    try:
        with _runner_seams(launch), patch("phase_loop_runtime.runner._parsed_child_automation", side_effect=parsed):
            snapshot, _results = runner.run_loop(repo, roadmap, phase="RUNNER", executor="codex")
    finally:
        if "armed" in state:
            state["armed"].__exit__(None, None, None)
    return snapshot, launches, state


def test_delegated_worker_fault_blocks_the_parent_and_launches_no_child():
    with tempfile.TemporaryDirectory() as td:
        snapshot, launches, _state = _run_delegated(td, arm_after_parent_launch=lambda: _worker_fault("phase_loop_closeout_request"))
    assert len(launches) == 1, "the delegated child was launched"
    assert snapshot.phases["RUNNER"] == "blocked"
    assert snapshot.blocker_class == "unretryable_external_outage", snapshot.blocker_summary
    assert "NOT launched" in snapshot.blocker_summary


def test_delegated_over_the_cap_is_a_contract_bug_and_launches_no_child():
    """#27: a real cap failure on the delegated path."""
    with tempfile.TemporaryDirectory() as td:
        snapshot, launches, _state = _run_delegated(td, arm_after_parent_launch=lambda: _lowered_cap(64))
    assert len(launches) == 1
    assert snapshot.phases["RUNNER"] == "blocked"
    assert snapshot.blocker_class == "contract_bug"
    assert "NOT launched" in snapshot.blocker_summary and "render refused" in snapshot.blocker_summary


def test_delegated_post_launch_fault_is_recorded_on_the_child():
    """A fault AFTER the child launched is the child's closeout parse, never
    'delegated child NOT launched'."""
    with tempfile.TemporaryDirectory() as td:
        snapshot, launches, state = _run_delegated(
            td, arm_after_parent_launch=lambda: _worker_fault("phase_loop_parse_closeout")
        )
    assert len(launches) == 2, snapshot.blocker_summary
    child = state["child"]
    assert child["automation_parse_error_blocker_class"] == "unretryable_external_outage"
    assert snapshot.phases["RUNNER"] == "blocked"
    assert "NOT launched" not in (snapshot.blocker_summary or "")


@pytest.mark.parametrize("failure", ["worker", "cap"])
def test_lane_entry_point_propagates_and_spawns_nothing(failure):
    from phase_loop_runtime.models import HarnessLaneAssignment

    with tempfile.TemporaryDirectory() as td:
        repo, roadmap, plans = _repo(td, ("RUNNER",))
        assignment = HarnessLaneAssignment(
            phase="RUNNER", lane_id="SL-0", work_unit_kind="lane_execute", owned_files=("src/runner.py",)
        )
        launched: list = []
        fault = _worker_fault("phase_loop_closeout_request") if failure == "worker" else _lowered_cap(64)
        with _runner_seams(_launch_returning(_native_closeout(), launched)), fault:
            exc = _raises(
                runner.launch_harness_lane_work_unit,
                repo=repo, roadmap=roadmap, plan=plans["RUNNER"], assignment=assignment, dry_run=False,
            )
    assert type(exc) is (BamlWorkerError if failure == "worker" else BamlValidationError), exc
    assert launched == []


# ---------------------------------------------------------------------------
# structural tripwires over src/
# ---------------------------------------------------------------------------


def _callee(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _direct_sites() -> set[str]:
    sites = set()
    for path in sorted(PKG.rglob("*.py")):
        stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                name = _callee(node)
                if name in REACHING:
                    sites.add(f"{path.relative_to(PKG)}::{'.'.join(stack) or '<module>'}::{name}")
                self.generic_visit(node)

        Visitor().visit(ast.parse(path.read_text(encoding="utf-8")))
    return sites


def test_every_direct_baml_call_site_is_in_the_caller_table():
    data = json.loads(CALL_SITES.read_text(encoding="utf-8"))
    listed = data["sites"]
    found = _direct_sites()
    assert found - set(listed) == set(), f"unlisted BAML call sites: {sorted(found - set(listed))}"
    assert set(listed) - found == set(), f"stale caller-table entries: {sorted(set(listed) - found)}"
    assert set(listed.values()) <= set(data["rows"])


def _handler_names(node) -> set[str]:
    if node is None:
        return {"BaseException"}
    if isinstance(node, ast.Tuple):
        return set().union(*(_handler_names(e) for e in node.elts))
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    return set()


def _unguarded_handlers() -> set[tuple[str, str, str]]:
    broad = {"BamlValidationError", "ValueError", "Exception", "BaseException"}
    found = set()
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Try):
                    continue
                if not any(isinstance(c, ast.Call) and _callee(c) in REACHING for s in node.body for c in ast.walk(s)):
                    continue
                guarded = False
                for handler in node.handlers:
                    names = _handler_names(handler.type)
                    if "BamlWorkerError" in names:
                        guarded = True
                    elif names & broad and not guarded:
                        found.add((str(path.relative_to(PKG)), function.name, ",".join(sorted(names))))
    return found


def test_broad_handlers_around_baml_calls_put_the_worker_error_first():
    allow = {
        (e["file"], e["function"], e["handler"])
        for e in json.loads(HANDLER_ALLOWLIST.read_text(encoding="utf-8"))["entries"]
    }
    assert _unguarded_handlers() - allow == set()


def test_the_handler_tripwire_sees_a_removed_guard(tmp_path, monkeypatch):
    """Falsifier for the tripwire itself: drop the runner's guard and it fires."""
    copy = tmp_path / "phase_loop_runtime"
    copy.mkdir()
    source = (TESTS.parent / "src" / "phase_loop_runtime" / "runner.py").read_text(encoding="utf-8")
    mutated = source.replace("    except BamlWorkerError as exc:\n        # agent-harness#1135 (#24)", "    except KeyError as exc:\n        # agent-harness#1135 (#24)", 1)
    assert mutated != source
    (copy / "runner.py").write_text(mutated, encoding="utf-8")
    monkeypatch.setitem(globals(), "PKG", copy)
    assert ("runner.py", "_parse_native_closeout_status", "BamlValidationError") in _unguarded_handlers()


def test_injection_no_longer_swallows_the_render_failure():
    """#22: the v0 fallback instruction is gone."""
    from phase_loop_runtime import injection

    source = Path(injection.__file__).read_text(encoding="utf-8")
    assert "BAML prompt render failed" not in source
    with _lowered_cap(64):
        exc = _raises(
            injection._render_baml_closeout_instruction, phase_alias="P", plan_produces=("G",), plan_owned_files=("a.py",)
        )
    assert type(exc) is BamlValidationError


def test_worker_kill_helper_really_kills():
    """Guard for this module's fault fixture: the worker dies by SIGKILL."""
    with _worker_fault("phase_loop_parse_closeout") as killer:
        exc = _raises(m.parse_baml_response, "EmitPhaseCloseout", OK)
    assert type(exc) is BamlWorkerError and exc.rc == -signal.SIGKILL and len(killer.killed) == 1


# ---------------------------------------------------------------------------
# codex hb1 B2: no later candidate or incomplete-turn rule overwrites an outage
# ---------------------------------------------------------------------------


def _failing_first_spawn():
    """Spawn failure on the first spawn only (a real missing-interpreter error),
    then the real worker: the second candidate WOULD parse cleanly."""
    real = m._spawn_popen
    used = {"n": 0}

    def spawn(argv, **kwargs):
        used["n"] += 1
        if used["n"] == 1:
            argv = ["/nonexistent/phase-loop/python3", *argv[1:]]
        return real(argv, **kwargs)

    return spawn


def _spec(executor: str):
    from types import SimpleNamespace

    return SimpleNamespace(executor=executor, prompt_bundle=SimpleNamespace(workflow_command="execute"))


def test_outage_on_the_first_candidate_is_not_overwritten_by_the_retained_log(tmp_path):
    log = tmp_path / "executor.log"
    log.write_text("log preamble\n" + _native_closeout(), encoding="utf-8")
    result = LaunchResult(command=["claude"], returncode=0, output=_native_closeout(), executor="claude", log_path=str(log))
    _use(None, retries=0)
    with patch.object(m, "_spawn_popen", _failing_first_spawn()):
        parsed = runner._parsed_child_automation(result, _spec("claude"))
    assert parsed["automation_status"] == "blocked", parsed.get("automation_status")
    assert parsed["automation_parse_error_blocker_class"] == "unretryable_external_outage"
    assert parsed["automation_blocker_class"] == "unretryable_external_outage"


def test_outage_survives_the_codex_incomplete_turn_rule():
    result = LaunchResult(
        command=["codex"], returncode=1, output="", executor="codex",
        codex_turn_completion={"completed": False}, codex_final_message=_native_closeout(),
    )
    _use(None, retries=0)
    with patch.object(m, "_spawn_popen", _failing_first_spawn()):
        parsed = runner._parsed_child_automation(result, _spec("codex"))
    assert parsed["automation_parse_error_blocker_class"] == "unretryable_external_outage"
    assert parsed["automation_blocker_class"] == "unretryable_external_outage"


# ---------------------------------------------------------------------------
# codex hb1 B3: a client-machinery failure is an outage end to end, never a
# fail-open 'uncertain' Tier-3 result or a content verdict
# ---------------------------------------------------------------------------


def test_tier3_blocks_on_a_client_machinery_failure():
    _use(None)
    with tempfile.TemporaryDirectory() as td, patch.object(m, "_read_raw_baml_files", side_effect=OSError(5, "I/O error")):
        audit = evidence_audit.run_tier3_runner_audit(_tier3_repo(td), tier3_budget=1, dirty_only=False)
    assert audit.blocker is not None and audit.blocker["blocker_class"] == "unretryable_external_outage"
    assert audit.warnings == () and audit.invocations == ()


def test_closeout_parse_is_not_evaluated_on_a_client_machinery_failure():
    _use(None)
    with patch.object(m, "_read_raw_baml_files", side_effect=OSError(5, "I/O error")):
        parsed = runner._parse_native_closeout_status(OK)
    assert parsed["automation_parse_error_blocker_class"] == "unretryable_external_outage"
