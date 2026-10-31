from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import stat
import threading

import pytest
import rfc8785

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


def verified_runtime_package(monkeypatch, root: Path) -> tuple[QualifiedRuntimePackage, Path]:
    package_root = root / "runtime"
    module = package_root / "phase_loop_runtime/executable_dependency_startup.py"
    metadata = package_root / "phase_loop_runtime-0.7.27.dist-info"
    record = metadata / "RECORD"
    python = root / "python3.14"
    module.parent.mkdir(parents=True)
    metadata.mkdir()
    module.write_bytes(b"runtime-module\n")
    (metadata / "METADATA").write_bytes(b"Name: phase-loop-runtime\nVersion: 0.7.27\n")
    record.write_bytes(b"canonical-record\n")
    python.write_bytes(b"synthetic-python\n")
    python.chmod(0o755)

    def digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    rows = [
        {
            "path": path.relative_to(package_root).as_posix(),
            "sha256": digest(path.read_bytes()),
            "size": path.stat().st_size,
        }
        for path in package_root.rglob("*")
        if path.is_file()
    ]
    rows.sort(key=lambda item: item["path"].encode("ascii"))
    metadata_path = metadata.relative_to(package_root).as_posix()
    metadata_rows = [row for row in rows if row["path"].startswith(metadata_path + "/")]
    files_sha256 = digest(rfc8785.dumps(rows))
    metadata_sha256 = digest(rfc8785.dumps(metadata_rows))
    root_stat = package_root.stat()
    manifest = {
        "schema": "org.agent-harness.installed-package-tree.v1",
        "distribution": "phase-loop-runtime",
        "version": "0.7.27",
        "install_root": {
            "path": str(package_root),
            "device": root_stat.st_dev,
            "inode": root_stat.st_ino,
            "uid": root_stat.st_uid,
            "gid": root_stat.st_gid,
            "mode": f"0{stat.S_IMODE(root_stat.st_mode):03o}",
        },
        "coverage": {
            "regular_files": "include-all",
            "symlinks": "reject",
            "bytecode": "include-if-present",
            "generated_files": "include-if-present",
            "special_files": "reject",
        },
        "distribution_metadata": {
            "path": metadata_path,
            "metadata_sha256": metadata_sha256,
            "record_path": record.relative_to(package_root).as_posix(),
            "record_sha256": digest(record.read_bytes()),
        },
        "files_sha256": files_sha256,
        "files": rows,
    }
    python_stat = python.stat()
    monkeypatch.setattr(startup, "__file__", str(module))
    monkeypatch.setattr(startup, "__version__", "0.7.27")
    monkeypatch.setattr(startup.sys, "executable", str(python))
    return QualifiedRuntimePackage(
        distribution="phase-loop-runtime",
        version="0.7.27",
        install_root=str(package_root),
        install_root_device=root_stat.st_dev,
        install_root_inode=root_stat.st_ino,
        installed_tree_manifest_id=digest(rfc8785.dumps(manifest)),
        installed_tree_files_sha256=files_sha256,
        distribution_metadata_sha256=metadata_sha256,
        distribution_record_path=record.relative_to(package_root).as_posix(),
        distribution_record_sha256=digest(record.read_bytes()),
        python_executable=str(python),
        python_executable_device=python_stat.st_dev,
        python_executable_inode=python_stat.st_ino,
        python_executable_size=python_stat.st_size,
        python_executable_sha256=digest(python.read_bytes()),
        private_runtime_binding_sha256="6" * 64,
    ), module


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


@pytest.mark.parametrize(
    "argv",
    (
        ["agy-canary-probe", "--evidence-root", "/synthetic"],
        ["agy-qualification", "run"],
        ["cli-qualification", "status", "--harness", "gemini"],
        ["future-provider-command"],
    ),
    ids=("agy-canary", "agy-qualification", "cli-qualification", "unknown-command"),
)
def test_required_session_refuses_unwired_or_unknown_cli_before_any_effect(
    monkeypatch,
    argv,
) -> None:
    dependency = FakeDependency()
    session = register_session(dependency)
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda package: None)
    effects: list[str] = []
    monkeypatch.setattr("phase_loop_runtime.cli.main", lambda _argv: effects.append("cli") or 0)
    try:
        with pytest.raises(ExecutableDependencyError, match="dependency_route_unwired"):
            session.run_cli(argv)
        assert effects == []
        assert dependency.revalidations == 0
        assert not session._tasks
    finally:
        session.close()


def test_standalone_session_preserves_unknown_cli_parser_dispatch(monkeypatch) -> None:
    session = DependencyStartupSession(runtime_package=runtime_package(), dependency=None)
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda package: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "phase_loop_runtime.cli.main",
        lambda argv: calls.append(list(argv)) or 2,
    )
    try:
        assert session.run_cli(["future-provider-command"]) == 2
        assert calls == [["future-provider-command"]]
    finally:
        session.close()


def test_cli_command_inventory_has_one_closed_dependency_classification(monkeypatch) -> None:
    from phase_loop_runtime import cli

    monkeypatch.delenv("PHASE_LOOP_PROFILE_PLUGINS", raising=False)
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(getattr(action, "choices", None), dict)
    )
    actual = set(subparsers.choices)
    assert startup._CLI_CLASSIFIED_COMMANDS <= actual
    assert all(
        startup._classify_cli_route([command]) == "dependency_unwired"
        for command in actual - startup._CLI_CLASSIFIED_COMMANDS
    )
    classes = (
        startup._CLI_DEPENDENCY_WIRED_COMMANDS,
        startup._CLI_DEPENDENCY_UNWIRED_COMMANDS,
        startup._CLI_CONDITIONAL_COMMANDS,
        startup._CLI_PROVIDER_FREE_COMMANDS,
    )
    assert sum(len(item) for item in classes) == len(set().union(*classes))
    assert startup._classify_cli_route(["agy-canary-probe", "--help"]) == "dependency_unwired"
    assert startup._classify_cli_route(["seat-sandbox", "qualify"]) == "dependency_wired"
    assert startup._classify_cli_route(["seat-sandbox", "token-status"]) == "provider_free"
    assert startup._classify_cli_route(["new-command", "--help"]) == "dependency_unwired"
    assert startup._classify_cli_route(["new-command", "run"]) == "dependency_unwired"
    assert startup._classify_cli_route(["new-command", "doctor"]) == "dependency_unwired"
    assert startup._classify_cli_route(["--repo", "/synthetic", "run"]) == "dependency_wired"
    assert startup._classify_cli_route(["--repo", "/synthetic", "doctor"]) == "provider_free"
    assert startup._classify_cli_route(["--future-option", "run"]) == "dependency_unwired"


def test_cli_global_option_arity_matches_the_actual_parser_actions(monkeypatch) -> None:
    from phase_loop_runtime import cli

    monkeypatch.delenv("PHASE_LOOP_PROFILE_PLUGINS", raising=False)
    parser = cli.build_parser()
    actual_flags: set[str] = set()
    actual_values: set[str] = set()
    for action in parser._actions:
        for option in action.option_strings:
            if option in {"-h", "--help", "--version"}:
                continue
            assert option.startswith("--"), f"unclassified short global option: {option}"
            (actual_flags if action.nargs == 0 else actual_values).add(option)
    assert actual_flags == startup._CLI_GLOBAL_FLAG_OPTIONS
    assert actual_values == startup._CLI_GLOBAL_VALUE_OPTIONS


def test_session_exit_preserves_primary_exception_and_attaches_cleanup_failure() -> None:
    session = register_session(FakeDependency())
    lease = session.acquire_task("still-live")
    try:
        with pytest.raises(RuntimeError, match="primary") as excinfo:
            with session:
                raise RuntimeError("primary")
        assert any("task_live" in note for note in excinfo.value.__notes__)
        assert not session.closed
    finally:
        lease.release()
        session.close()


def test_runtime_binding_digest_is_opaque_but_still_hash_typed(monkeypatch) -> None:
    package = runtime_package()
    monkeypatch.setattr(startup, "__version__", package.version)
    with pytest.raises(ExecutableDependencyError, match="runtime_mismatch"):
        startup._validate_runtime_package(replace(package, private_runtime_binding_sha256="opaque"))


def test_runtime_package_recomputes_manifest_and_refuses_mismatch_or_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package, module = verified_runtime_package(monkeypatch, tmp_path)
    startup._validate_runtime_package(package)
    with pytest.raises(ExecutableDependencyError, match="installed tree manifest"):
        startup._validate_runtime_package(replace(package, installed_tree_manifest_id="f" * 64))
    module.write_bytes(b"mutated-runtime-module\n")
    with pytest.raises(ExecutableDependencyError, match="installed tree"):
        startup._validate_runtime_package(package)
