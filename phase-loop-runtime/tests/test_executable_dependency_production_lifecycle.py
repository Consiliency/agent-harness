from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime import executable_dependency_startup as startup
from phase_loop_runtime import launcher, panel_invoker, seat_jail
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime.executable_dependency_startup import (
    DependencyStartupSpec,
    QualifiedRuntimePackage,
    current_dependency_for_provider,
    open_dependency_startup,
)


def _runtime_package() -> QualifiedRuntimePackage:
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


def _tree_digest(tree: Path) -> str:
    descriptor = seat_jail.open_dir_nofollow(tree)
    try:
        return seat_jail.tree_manifest_sha256_at(descriptor)
    finally:
        os.close(descriptor)


def _assert_descriptors_closed(descriptors: tuple[int, ...]) -> None:
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_managed_launcher_and_production_jails_share_one_dependency_lifetime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path / "fixture", layout="layout-b", provider="claude")
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda _package: None)
    session = open_dependency_startup(
        DependencyStartupSpec(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
            _runtime_package(),
        )
    )
    dependency = session.dependency
    assert dependency is not None
    launched: list[tuple[list[str], dict[str, object]]] = []
    probed: list[tuple[tuple[str, ...], tuple[int, ...]]] = []
    qualified: list[seat_jail.SeatJail] = []
    provider_spawns: list[bool] = []
    closed_descriptors: list[tuple[int, ...]] = []

    monkeypatch.setattr(
        panel_invoker._seat_credentials,
        "resolve_claude_seat_credential",
        lambda *_args, **_kwargs: SimpleNamespace(
            token=b"synthetic-token",
            source="synthetic",
            expires_at=None,
            notices=(),
        ),
    )
    monkeypatch.setattr(
        panel_invoker,
        "_require_qualified_jail",
        lambda jail: qualified.append(jail),
    )
    monkeypatch.setattr(
        panel_invoker,
        "_require_jailed_seat_identity",
        lambda prefix, _jail, pass_fds, _env: probed.append((tuple(prefix), tuple(pass_fds))),
    )
    monkeypatch.setattr(
        panel_invoker.subprocess,
        "Popen",
        lambda argv, **kwargs: launched.append((list(argv), dict(kwargs))) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        panel_invoker,
        "_count_provider_spawn",
        lambda: provider_spawns.append(True),
    )

    def fake_launch(command, **_kwargs):
        launched.append((list(command), {"boundary": "launcher"}))
        return launcher.LaunchResult(command=list(command), returncode=0)

    monkeypatch.setattr(launcher, "_resolve_command_context", lambda spec, *_a, **_k: (list(spec.command), []))
    monkeypatch.setattr(launcher, "launch", fake_launch)
    monkeypatch.setattr(launcher, "_result_with_spec", lambda result, _spec: result)

    spec = SimpleNamespace(
        executor="claude",
        command=[str(fixture.subject), "--synthetic"],
        prompt_bundle=SimpleNamespace(product_action="execute"),
        available=True,
        claude_route=None,
        delivery_mode="argv",
        wrapped_cwd=None,
        launch_timeout_seconds=None,
        cleanup_paths=(),
    )

    def managed_main(_argv: list[str]) -> int:
        assert len(session._tasks) == 1
        assert current_dependency_for_provider("claude") is dependency
        result = launcher.launch_with_spec(spec)
        assert result.returncode == 0

        review = tmp_path / "review"
        tree = review / seat_jail.HOST_TREE_DIRNAME
        tree.mkdir(parents=True, mode=0o700)
        (tree / "subject.txt").write_text("synthetic review\n", encoding="utf-8")
        authorization = SimpleNamespace(staged_tree_sha256=_tree_digest(tree))
        production = probe = None
        try:
            prepared = panel_invoker._prepare_jailed_claude(
                review,
                tmp_path / "seat",
                authorization,
                1,
                os.getpid(),
                ("synthetic artifact", "synthetic instructions"),
            )
            production, probe = prepared.jail, prepared.probe_jail
            assert production.dependency is probe.dependency is dependency
            assert production.dependency_projection_digest == dependency.projection_digest
            assert probe.dependency_projection_digest == dependency.projection_digest
            assert set(production.dependency_fds).isdisjoint(probe.dependency_fds)
            assert production.dependency_destinations == probe.dependency_destinations
            assert production.dependency_mount_points == probe.dependency_mount_points
            assert seat_jail.actual_profile_digest(production) == seat_jail.jail_profile_digest("claude")
            assert seat_jail.actual_profile_digest(probe) == seat_jail.jail_profile_digest("claude")
            for descriptor in (*production.dependency_fds, *probe.dependency_fds):
                os.fstat(descriptor)

            egress = panel_invoker._EGRESS_LAUNCH_PREFIX.set(
                ("/usr/bin/nsenter", "--net=/proc/1/ns/net", "/usr/bin/setpriv", "--")
            )
            try:
                panel_invoker.launch_provider(
                    [production.provider_argv0, "--synthetic"],
                    process_owner=production,
                    probe_owner=probe,
                    env={},
                )
                assert qualified == [production]
                assert len(probed) == 1
                assert probed[0][1] == probe.pass_fds
                assert launched[-1][1]["pass_fds"] == production.pass_fds
                assert provider_spawns == [True]

                effects_before_refusal = (
                    len(qualified),
                    len(probed),
                    len(launched),
                    len(provider_spawns),
                )
                fixture.helper.write_bytes(b"changed-before-launch")
                with pytest.raises(ExecutableDependencyError, match="source_changed"):
                    panel_invoker.launch_provider(
                        [production.provider_argv0],
                        process_owner=production,
                        probe_owner=probe,
                        env={},
                    )
                assert effects_before_refusal == (
                    len(qualified),
                    len(probed),
                    len(launched),
                    len(provider_spawns),
                )
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(egress)
        finally:
            if probe is not None:
                closed_descriptors.append(probe.pass_fds)
                seat_jail.close_jail_fds(probe)
            if production is not None:
                closed_descriptors.append(production.pass_fds)
                seat_jail.close_jail_fds(production)
        return 0

    monkeypatch.setattr("phase_loop_runtime.cli.main", managed_main)
    try:
        assert session.run_cli(["run"]) == 0
        assert not session._tasks
        for descriptors in closed_descriptors:
            _assert_descriptors_closed(descriptors)
        os.fstat(fixture.authority_fd)
        session.close()
        assert dependency.closed
        os.fstat(fixture.authority_fd)
    finally:
        if not session.closed:
            session.close()
        fixture.close()


def test_missing_authority_refuses_before_credentials_outputs_or_processes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path / "fixture", provider="claude")
    effects: list[str] = []
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda _package: None)
    monkeypatch.setattr(
        panel_invoker._seat_credentials,
        "resolve_claude_seat_credential",
        lambda *_a, **_k: effects.append("credential"),
    )
    monkeypatch.setattr(
        panel_invoker,
        "_precreate_seat_output",
        lambda *_a, **_k: effects.append("output"),
    )
    monkeypatch.setattr(
        panel_invoker.subprocess,
        "Popen",
        lambda *_a, **_k: effects.append("process"),
    )
    monkeypatch.setattr("phase_loop_runtime.cli.main", lambda _argv: effects.append("cli") or 0)
    try:
        with pytest.raises(ExecutableDependencyError, match="authority_missing"):
            open_dependency_startup(
                DependencyStartupSpec(
                    fixture.requirement,
                    None,
                    None,
                    _runtime_package(),
                )
            )
        assert effects == []
        assert not (tmp_path / "seat").exists()
    finally:
        fixture.close()


def test_launcher_rechecks_subject_path_inode_at_final_process_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path / "fixture", provider="claude")
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda _package: None)
    session = open_dependency_startup(
        DependencyStartupSpec(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
            _runtime_package(),
        )
    )
    launched: list[list[str]] = []
    monkeypatch.setattr(
        launcher,
        "_resolve_command_context",
        lambda spec, *_args, **_kwargs: (list(spec.command), []),
    )
    monkeypatch.setattr(
        launcher,
        "launch",
        lambda command, **_kwargs: launched.append(list(command)),
    )

    def swap_after_initial_validation() -> str:
        original = fixture.subject.read_bytes()
        fixture.release.rename(fixture.release.with_name("held-release"))
        fixture.subject.parent.mkdir(parents=True)
        fixture.subject.write_bytes(original)
        fixture.subject.chmod(0o755)
        return "synthetic-input"

    spec = SimpleNamespace(
        executor="claude",
        command=[str(fixture.subject), "--synthetic"],
        prompt_bundle=SimpleNamespace(product_action="execute"),
        available=True,
        claude_route=None,
        delivery_mode="stdin",
        delivery_payload=swap_after_initial_validation,
        wrapped_cwd=None,
        launch_timeout_seconds=None,
        cleanup_paths=(),
    )

    def managed_main(_argv: list[str]) -> int:
        with pytest.raises(ExecutableDependencyError, match="source_changed"):
            launcher.launch_with_spec(spec)
        return 0

    monkeypatch.setattr("phase_loop_runtime.cli.main", managed_main)
    try:
        assert session.run_cli(["run"]) == 0
        assert launched == []
    finally:
        session.close()
        fixture.close()


def test_panel_cancellation_releases_child_task_and_projection_descriptors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path / "fixture", provider="claude")
    monkeypatch.setattr(startup, "_validate_runtime_package", lambda _package: None)
    session = open_dependency_startup(
        DependencyStartupSpec(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
            _runtime_package(),
        )
    )
    dependency = session.dependency
    assert dependency is not None
    cancelled = threading.Event()
    reopened: list[tuple[int, ...]] = []

    def managed_main(_argv: list[str]) -> int:
        assert len(session._tasks) == 1

        def cancel_leg(_item: object) -> panel_invoker.PanelLegResult:
            assert current_dependency_for_provider("claude") is dependency
            with dependency.reopen_projection() as projection:
                descriptors = projection.pass_fds
                reopened.append(descriptors)
                for descriptor in descriptors:
                    os.fstat(descriptor)
                raise panel_invoker._ReviewOperationCancelled("review_operation_cancelled")

        with pytest.raises(panel_invoker._ReviewOperationCancelled, match="review_operation_cancelled"):
            panel_invoker._run_legs_ordered(
                ["claude"],
                cancel_leg,
                max_concurrency=1,
                cancel_event=cancelled,
            )
        assert cancelled.is_set()
        assert len(session._tasks) == 1
        for descriptors in reopened:
            _assert_descriptors_closed(descriptors)
        return 0

    monkeypatch.setattr("phase_loop_runtime.cli.main", managed_main)
    try:
        assert session.run_cli(["run"]) == 0
        assert not session._tasks
        session.close()
        assert dependency.closed
    finally:
        if not session.closed:
            session.close()
        fixture.close()
