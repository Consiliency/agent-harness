from __future__ import annotations

from pathlib import Path
import threading

import pytest

from phase_loop_runtime import executable_dependency_startup as startup
from phase_loop_runtime import panel_invoker, worker_pool
from phase_loop_runtime.convergence.dispatch import RepositoryDispatchRequest, dispatch_ready_nodes
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime.executable_dependency_startup import DependencyStartupSession
from phase_loop_runtime.launcher import LaunchResult
from phase_loop_runtime.train_ledger import ConvergenceResultEnvelope, ConvergenceResultStatus
from test_executable_dependency_startup import FakeDependency, runtime_package


def session_with_parent():
    dependency = FakeDependency()
    session = DependencyStartupSession(
        runtime_package=runtime_package(),
        dependency=dependency,  # type: ignore[arg-type]
    )
    startup._ACTIVE_REQUIRED[session.session_id] = session
    parent = session.acquire_task("parent")
    return dependency, session, parent


def finish(session: DependencyStartupSession, parent) -> None:
    if not parent.released:
        parent._release_if_pending()
    for task in tuple(session._tasks.values()):
        task._release_if_pending()
    session.close()


def test_worker_pool_binds_one_explicit_child_per_job(monkeypatch, tmp_path: Path) -> None:
    dependency, session, parent = session_with_parent()
    seen: list[int] = []

    def fake_launch(*_args, **_kwargs) -> LaunchResult:
        assert startup.current_dependency_for_provider("synthetic") is dependency
        seen.append(threading.get_ident())
        return LaunchResult(command=[], returncode=0, executor="synthetic")

    monkeypatch.setattr(worker_pool, "launch_with_spec", fake_launch)
    try:
        with parent.bind_current():
            jobs = [
                worker_pool.PhaseWorkerJob(
                    phase=f"phase-{index}",
                    spec=object(),  # type: ignore[arg-type]
                    dependency_task=session.acquire_task(f"worker:{index}"),
                )
                for index in range(2)
            ]
            results = worker_pool.run_phase_worker_pool(
                tmp_path,
                tmp_path / "roadmap.md",
                jobs,
                max_workers=2,
            )
        parent.release()
        assert [result.phase for result in results] == ["phase-0", "phase-1"]
        assert len(seen) == 2
        assert not session._tasks
    finally:
        finish(session, parent)


def test_panel_legs_bind_and_release_children_on_success_and_exception() -> None:
    dependency, session, parent = session_with_parent()
    try:
        with parent.bind_current():
            results = panel_invoker._run_legs_ordered(
                [0, 1],
                lambda item: (
                    startup.current_dependency_for_provider("synthetic"), item
                )[1],
                max_concurrency=2,
            )
            assert results == [0, 1]
            with pytest.raises(ValueError, match="synthetic failure"):
                panel_invoker._run_legs_ordered(
                    [0, 1],
                    lambda item: (_ for _ in ()).throw(ValueError("synthetic failure")),
                    max_concurrency=1,
                )
            assert set(session._tasks) == {"parent"}
        parent.release()
    finally:
        finish(session, parent)


def test_convergence_dispatch_binds_each_execute_callback() -> None:
    dependency, session, parent = session_with_parent()
    requests = [
        RepositoryDispatchRequest(
            node_id=f"node-{index}",
            repository=f"repo-{index}",
            owned_paths=(f"path-{index}",),
            frozen_shared_interfaces=True,
        )
        for index in range(2)
    ]

    def execute(request: RepositoryDispatchRequest) -> ConvergenceResultEnvelope:
        assert startup.current_dependency_for_provider("synthetic") is dependency
        return ConvergenceResultEnvelope(ConvergenceResultStatus.COMPLETED, request.node_id)

    try:
        with parent.bind_current():
            results = dispatch_ready_nodes(requests, execute, max_workers=2)
        parent.release()
        assert set(results) == {"node-0", "node-1"}
        assert not session._tasks
    finally:
        finish(session, parent)


def test_thread_without_explicit_child_refuses_while_required_session_is_active() -> None:
    _dependency, session, parent = session_with_parent()
    failures: list[str] = []

    def unbound() -> None:
        try:
            startup.current_dependency_for_provider("synthetic")
        except ExecutableDependencyError as exc:
            failures.append(exc.code)

    try:
        with parent.bind_current():
            thread = threading.Thread(target=unbound)
            thread.start()
            thread.join(timeout=5)
        parent.release()
        assert failures == ["task_unbound"]
    finally:
        finish(session, parent)
