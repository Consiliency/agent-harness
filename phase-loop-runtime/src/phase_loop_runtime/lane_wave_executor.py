"""Execute isolated lane waves after the runner's ordinary dispatch gates.

The journal deliberately has no automatic recovery: uncertain child/transport
state is evidence, never permission to launch another writer.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .discovery import _owned_pattern_matches
from .lane_scheduler import select_ready_lane_wave, validate_concurrent_lane_ownership, worktree_assignments_for_wave
from .models import HarnessLaneAssignment
from .observability import run_artifacts, stop_requested
from .phase_worktree_executor import (
    create_phase_worktree, current_branch, reclaim_phase_worktree,
    resolve_base_sha, teardown_phase_worktree, transfer_phase_worktree_dirty,
)
from .plan_ir import parse_phase_plan_ir
from .runtime_paths import phase_loop_dir
from .worker_pool import PhaseWorkerJob, run_phase_worker_pool


@dataclass(frozen=True)
class LaneExecutionResult:
    status: str  # serial, preview, complete, blocked
    reason: str
    metadata: dict


def _git(repo: Path, *args: str, env=None) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], env=env, text=True, stderr=subprocess.PIPE).strip()


def snapshot_lane_outputs(repo: Path, head: str, paths: list[str]) -> str:
    """HEAD plus accepted outputs only; never borrow the parent's index."""
    if not paths:
        return head
    with tempfile.TemporaryDirectory(prefix="lane-index-") as temporary:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        _git(repo, "read-tree", head, env=env)
        _git(repo, "add", "--all", "--", *paths, env=env)
        tree = _git(repo, "write-tree", env=env)
        return _git(repo, "commit-tree", tree, "-p", head, "-m", "Lane dependency snapshot", env=env)


def _write_journal(path: Path, journal: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".journal-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(journal, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def lane_recovery_blocker(repo: Path, phase: str) -> dict:
    """Return recovery evidence; unrelated work-unit modes are not lane writers."""
    from .state import load_work_unit_state
    units = [key for key, state in load_work_unit_state(repo).items()
             if state.identity.phase == phase and state.status in {"running", "awaiting-closeout"}
             and state.policy.get("source") == "lane_scheduler"
             and state.policy.get("mode") == "concurrent"
             and not state.policy.get("dry_run", False)]
    journals = []
    for path in (phase_loop_dir(repo) / "lane-attempts").glob("*.json"):
        try:
            journal = json.loads(path.read_text())
            if journal.get("phase") == phase and any(
                record.get("status") in {"running", "transport_intent", "blocked"}
                for record in journal.get("lanes", {}).values()
            ):
                journals.append(str(path))
        except (OSError, ValueError, TypeError, AttributeError):
            journals.append(str(path))
    return {"journal_paths": journals, "work_unit_ids": units} if journals or units else {}


def resumed_lane_executor(repo: Path, plan: Path, phase: str) -> str | None:
    """Keep a completed partial attempt's author across runner resumes."""
    identity = hashlib.sha256(plan.read_bytes()).hexdigest()
    head = resolve_base_sha(repo)
    selected = None
    paths = (phase_loop_dir(repo) / "lane-attempts").glob("*.json")
    for path in sorted(paths, key=lambda item: item.stat().st_mtime):
        journal = json.loads(path.read_text())
        if (journal.get("phase"), journal.get("plan_identity"), journal.get("head")) == (phase, identity, head):
            if any(record.get("status") == "complete" for record in journal.get("lanes", {}).values()):
                selected = journal.get("executor")
    return selected


def execute_lane_waves(
    *, repo: Path, roadmap: Path, plan: Path, phase: str, executor: str,
    max_workers: int, prepare: Callable, trusted_closeout: Callable,
    event: Callable, dry_run: bool = False, pool: Callable = run_phase_worker_pool,
    caller_run_id: str | None = None,
) -> LaneExecutionResult:
    """Prepare a whole wave, drain it, then journal and transport each lane.

    ``prepare`` receives an actual creator-returned assignment and returns an
    already resolved launch spec. It must not launch a provider.
    """
    if max_workers < 1:
        raise ValueError("max_parallel_lanes must be positive")
    if recovery := lane_recovery_blocker(repo, phase):
        return LaneExecutionResult("blocked", "lane_recovery_required", recovery)
    ir = parse_phase_plan_ir(plan)
    if ir.diagnostics or not ir.lanes:
        return LaneExecutionResult("serial", "no_verified_lanes", {})
    if any(lane.execution_policy and lane.execution_policy.executor not in {None, executor} for lane in ir.lanes):
        return LaneExecutionResult("serial", "executor_pin_conflict", {})
    head = resolve_base_sha(repo)
    plan_identity = hashlib.sha256(plan.read_bytes()).hexdigest()
    attempt = uuid.uuid4().hex
    journal = {"phase": phase, "executor": executor, "plan_identity": plan_identity, "attempt": attempt, "head": head, "lanes": {}}
    journal_path = phase_loop_dir(repo) / "lane-attempts" / f"{attempt}.json"
    completed: list[str] = []
    accepted_paths: list[str] = []
    for path in sorted(journal_path.parent.glob("*.json"), key=lambda p: p.stat().st_mtime):
        previous = json.loads(path.read_text())
        if (previous.get("phase"), previous.get("plan_identity"), previous.get("head")) == (phase, plan_identity, head):
            journal, journal_path = previous, path
            attempt = journal["attempt"]
    if journal.get("executor") != executor:
        return LaneExecutionResult("blocked", "executor_pin_conflict", journal)
    for lane_id, record in journal["lanes"].items():
        if record["status"] == "complete":
            completed.append(lane_id)
            accepted_paths.extend(record.get("paths", []))
    first = select_ready_lane_wave(ir, mode="concurrent", completed_lane_ids=tuple(completed))
    if len(completed) != len(ir.lanes):
        if first.status != "ready" or first.ready_wave is None:
            return LaneExecutionResult("serial", "ownership_ambiguous", {"decision": first.to_json()})
        if max_workers == 1 or (not completed and len(first.ready_wave.lane_ids) < 2):
            return LaneExecutionResult("serial", "serial_selection", {})
    if dry_run:
        return LaneExecutionResult("preview", "ready", {"decision": first.to_json(), "max_workers": max_workers})
    lane_by_id = {lane.lane_id: lane for lane in ir.lanes}
    started = bool(completed)
    while len(completed) < len(ir.lanes):
        decision = select_ready_lane_wave(ir, mode="concurrent", completed_lane_ids=tuple(completed))
        if decision.status != "ready" or decision.ready_wave is None:
            return LaneExecutionResult("blocked" if started else "serial", "ownership_ambiguous", journal)
        lanes = [lane_by_id[lane_id] for lane_id in decision.ready_wave.lane_ids[:max_workers]]
        handles, jobs, specs = {}, [], {}
        launched = False
        transferred = set()
        workers = {}
        try:
            try:
                base = snapshot_lane_outputs(repo, head, accepted_paths)
                branch = current_branch(repo)
                for lane in lanes:
                    job_id = f"{phase}-{lane.lane_id}-{attempt}"
                    handle = create_phase_worktree(repo, phase=job_id, target_branch=branch, base_sha=base)
                    handles[lane.lane_id] = handle
                assignments = worktree_assignments_for_wave(repo, lanes, branch=branch, mode="concurrent", handles=handles)
                if validate_concurrent_lane_ownership(lanes, assignments=assignments, expected_base_sha=base):
                    raise ValueError("invalid creator-returned assignments")
                if len({a.worktree_path for a in assignments}) != len(lanes):
                    raise ValueError("duplicate worktree assignment")
                for lane, assignment in zip(lanes, assignments):
                    handle = handles[lane.lane_id]
                    if resolve_base_sha(handle.worktree_path) != base:
                        raise ValueError("worktree base mismatch")
                    lane_assignment = HarnessLaneAssignment.from_lane(
                        phase=phase, lane=lane,
                        work_unit_kind=decision.ready_wave.work_unit_kinds[lane.lane_id],
                        worktree_assignment=assignment,
                        metadata={"plan_identity": plan_identity, "attempt": attempt,
                                  "closeout_mode": "manual", "phase_closeout_allowed": False},
                    )
                    spec = prepare(handle, lane_assignment)
                    if not spec.available:
                        raise ValueError("lane launch spec unavailable")
                    specs[lane.lane_id] = spec
                    artifacts = run_artifacts(repo, f"{phase}-{lane.lane_id}-{attempt}", "execute", len(completed) + 1, spec)
                    jobs.append(PhaseWorkerJob(
                        phase=f"{phase}-{lane.lane_id}-{attempt}", spec=spec, log_path=artifacts["log"],
                        heartbeat_path=artifacts["heartbeat"], worktree_handle=handle,
                        caller_run_id=caller_run_id, lease_authority=handle.lease_authority,
                    ))
                    journal["lanes"][lane.lane_id] = {
                        "status": "prepared", "base": base, "generation": handle.generation,
                        "worktree": str(handle.worktree_path), "branch": handle.temp_branch,
                        "artifacts": {k: str(v) for k, v in artifacts.items()},
                    }
            except Exception:
                # No child in this wave has started. Do not expose exception text
                # (which can contain host paths) in portable decision metadata.
                return LaneExecutionResult("blocked" if started else "serial", "worktree_unavailable", journal)
            if stop_requested(repo):
                return LaneExecutionResult("blocked", "operator_halt", journal)
            for lane in lanes:
                journal["lanes"][lane.lane_id]["status"] = "running"
            _write_journal(journal_path, journal)
            for lane in lanes:
                event(lane.lane_id, {"attempt": attempt, "plan_identity": plan_identity, "max_workers": max_workers})
            # Check again immediately before the bounded pool, not only before specs.
            if stop_requested(repo):
                for lane in lanes:
                    journal["lanes"][lane.lane_id]["status"] = "cancelled_before_launch"
                _write_journal(journal_path, journal)
                return LaneExecutionResult("blocked", "operator_halt", journal)
            launched = started = True
            pool_results = {worker.phase: worker for worker in pool(repo, roadmap, jobs, max_workers=max_workers)}
            workers = {lane.lane_id: pool_results.get(f"{phase}-{lane.lane_id}-{attempt}") for lane in lanes}
            for lane in lanes:
                record = journal["lanes"][lane.lane_id]
                worker = workers.get(lane.lane_id)
                if worker is None or not trusted_closeout(worker.result, specs[lane.lane_id]).get("closeout_trusted"):
                    record["status"] = "blocked"
                    _write_journal(journal_path, journal)
                    return LaneExecutionResult("blocked", "untrusted_lane_closeout", journal)
                record["status"] = "transport_intent"
                _write_journal(journal_path, journal)
                transfer = transfer_phase_worktree_dirty(
                    repo, handles[lane.lane_id],
                    owns_path=lambda path, patterns=lane.owned_files: path in patterns or any(_owned_pattern_matches(path, pattern) for pattern in patterns),
                )
                if not transfer.applied:
                    record["status"] = "blocked"
                    _write_journal(journal_path, journal)
                    return LaneExecutionResult("blocked", "lane_transport_refused", journal)
                changed = _git(handles[lane.lane_id].worktree_path, "diff", "--name-only", "-z", base, "HEAD")
                paths = [path for path in changed.split("\0") if path]
                accepted_paths.extend(paths)
                record.update(status="complete", paths=paths)
                _write_journal(journal_path, journal)
                completed.append(lane.lane_id)
                transferred.add(lane.lane_id)
        except Exception:
            # Running/intent records deliberately survive both launch and apply errors.
            return LaneExecutionResult("blocked", "lane_recovery_required", journal)
        finally:
            for lane_id, handle in handles.items():
                worker = workers.get(lane_id)
                if lane_id in transferred and worker is not None:
                    teardown_phase_worktree(repo, handle, transferred_to_parent=True,
                                            supervisor_receipt=worker.result.supervisor_receipt)
                authority = handle.lease_authority
                if authority is not None and authority.is_open():
                    authority.close()
                if not launched:
                    reclaim_phase_worktree(repo, handle)
    try:
        journal["integrated_snapshot"] = snapshot_lane_outputs(repo, head, accepted_paths)
        _write_journal(journal_path, journal)
    except (OSError, subprocess.SubprocessError):
        return LaneExecutionResult("blocked", "integrated_snapshot_unavailable", journal)
    return LaneExecutionResult("complete", "accepted", journal)
