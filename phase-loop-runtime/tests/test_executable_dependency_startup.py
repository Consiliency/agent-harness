from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import threading

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime import executable_dependency_startup as startup
from phase_loop_runtime.executable_dependency_startup import (
    DependencyStartupSession,
    DependencyStartupSpec,
    QualifiedRuntimePackage,
    current_dependency_for_provider,
    open_dependency_startup,
)


def runtime_package() -> QualifiedRuntimePackage:
    return QualifiedRuntimePackage(
        distribution="phase-loop-runtime",
        version="0.7.27",
        install_root="/synthetic/runtime",
        install_root_device=1,
        install_root_inode=2,
        installed_tree_manifest_id="1" * 64,
        installed_tree_files_sha256="2" * 64,
        distribution_metadata_sha256="3" * 64,
        distribution_record_path="phase_loop_runtime.dist-info/RECORD",
        distribution_record_sha256="4" * 64,
        python_executable="/synthetic/python",
        python_executable_device=1,
        python_executable_inode=3,
        python_executable_size=1,
        python_executable_sha256="5" * 64,
        private_runtime_binding_sha256="6" * 64,
    )


class FakeDependency:
    provider = "synthetic"
    projection_digest = "7" * 64

    def __init__(self) -> None:
        self.closed = False
        self.revalidations = 0

    def revalidate(self) -> None:
        if self.closed:
            raise ExecutableDependencyError("dependency_closed")
        self.revalidations += 1

    def validate_provider(self, provider: str) -> None:
        if provider != self.provider:
            raise ExecutableDependencyError("subject_mismatch")
        self.revalidate()

    def validate_command(self, command, *, provider=None) -> None:
        del command
        self.validate_provider(provider)

    def close(self) -> None:
        self.closed = True


def register_session(dependency: FakeDependency) -> DependencyStartupSession:
    session = DependencyStartupSession(
        runtime_package=runtime_package(),
        dependency=dependency,  # type: ignore[arg-type]
    )
    startup._ACTIVE_REQUIRED[session.session_id] = session
    return session


def test_requirement_is_independent_and_missing_authority_refuses(monkeypatch, tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "missing")
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda package: None)
    try:
        spec = DependencyStartupSpec(
            requirement=fixture.requirement,
            borrowed_authority_fd=None,
            expected_authority_sha256=None,
            runtime_package=runtime_package(),
        )
        with pytest.raises(ExecutableDependencyError, match="authority_missing"):
            open_dependency_startup(spec)
    finally:
        fixture.close()


def test_only_both_absent_selects_standalone(monkeypatch) -> None:
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda package: None)
    package = runtime_package()
    session = open_dependency_startup(
        DependencyStartupSpec(None, None, None, package)
    )
    session.close()
    with pytest.raises(ExecutableDependencyError, match="authority_invalid"):
        open_dependency_startup(DependencyStartupSpec(None, 9, "0" * 64, package))


def test_open_session_owns_duplicates_not_borrowed_authority(monkeypatch, tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "startup")
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda package: None)
    try:
        session = open_dependency_startup(
            DependencyStartupSpec(
                fixture.requirement,
                fixture.authority_fd,
                fixture.requirement.expected_authority_sha256,
                runtime_package(),
            )
        )
        session.close()
        os.fstat(fixture.authority_fd)
    finally:
        fixture.close()


def test_parent_reset_does_not_revoke_child_and_close_refuses_live_task() -> None:
    dependency = FakeDependency()
    session = register_session(dependency)
    parent = session.acquire_task("parent")
    try:
        with parent.bind_current():
            child = session.acquire_task("child")
        parent.release()
        with pytest.raises(ExecutableDependencyError, match="task_live"):
            session.close()

        seen: list[object] = []

        def run_child() -> None:
            with child.bind_current():
                seen.append(current_dependency_for_provider("synthetic"))
            child.release()

        thread = threading.Thread(target=run_child)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert seen == [dependency]
        session.close()
        assert dependency.closed
    finally:
        if not session.closed:
            for task in tuple(session._tasks.values()):
                task._release_if_pending()
            session.close()


def test_live_scope_replacement_and_duplicate_release_refuse() -> None:
    session = register_session(FakeDependency())
    first = session.acquire_task("first")
    second = session.acquire_task("second")
    try:
        with first.bind_current():
            with pytest.raises(ExecutableDependencyError, match="task_replacement"):
                with second.bind_current():
                    pass
        first.release()
        with pytest.raises(ExecutableDependencyError, match="duplicate release"):
            first.release()
        second.release()
    finally:
        session.close()


def test_provider_free_entry_uses_no_task_and_live_entry_binds_one(monkeypatch) -> None:
    dependency = FakeDependency()
    session = register_session(dependency)
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda package: None)
    calls: list[object] = []

    def fake_main(argv) -> int:
        calls.append(startup._CURRENT_TASK.get())
        if argv == ["run"]:
            assert current_dependency_for_provider("synthetic") is dependency
        return 0

    monkeypatch.setattr("phase_loop_runtime.cli.main", fake_main)
    try:
        assert session.run_cli(["doctor"]) == 0
        assert calls[-1] is None
        assert session.run_cli(["run"]) == 0
        assert calls[-1] is not None
        assert not session._tasks
    finally:
        session.close()


def test_runtime_binding_digest_is_opaque_but_still_hash_typed(monkeypatch) -> None:
    package = runtime_package()
    monkeypatch.setattr(startup, "__version__", package.version)
    with pytest.raises(ExecutableDependencyError, match="runtime_mismatch"):
        startup._validate_runtime_package(replace(package, private_runtime_binding_sha256="opaque"))
