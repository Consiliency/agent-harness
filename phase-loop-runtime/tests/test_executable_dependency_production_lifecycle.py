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


class _LegDependency:
    def __init__(self, refusal: str) -> None:
        self.refusal = refusal
        self.projection_digest = "a" * 64
        self.authority_sha256 = "b" * 64
        self.declaration_sha256 = "c" * 64
        self._runtime_euid_owned_sources = False
        self._runtime_euid_writable_sources = False

    def revalidate(self) -> None:
        if self.refusal == "source_changed":
            raise ExecutableDependencyError("source_changed", "/fixture/provider")


def _dummy_pipe_jail(dependency: object | None, projection_digest: str) -> SimpleNamespace:
    read_fd, write_fd = os.pipe()
    return SimpleNamespace(
        dependency=dependency,
        dependency_projection_digest=projection_digest,
        env={},
        profile_digest="d" * 64,
        profile_id="synthetic-profile",
        filter_digest="e" * 64,
        pass_fds=(read_fd, write_fd),
        provider_argv0="/run/phase-loop-seat/provider",
        redacted_owner=lambda: ["synthetic-owner"],
    )


@pytest.mark.parametrize("leg", ["claude", "gemini"])
@pytest.mark.parametrize("refusal", ["source_changed", "digest_changed"])
def test_jailed_leg_dependency_refusal_runs_real_descriptor_cleanup_before_boundary(
    monkeypatch,
    tmp_path: Path,
    leg: str,
    refusal: str,
) -> None:
    dependency = _LegDependency(refusal)
    production = _dummy_pipe_jail(
        dependency,
        dependency.projection_digest if refusal == "source_changed" else "f" * 64,
    )
    probe = _dummy_pipe_jail(None, "")
    descriptors = (*production.pass_fds, *probe.pass_fds)
    seat = panel_invoker._JailedSeat(
        jail=production,
        probe_jail=probe,
        holder_pid=123,
        token=b"synthetic-no-credential",
        review_dir=tmp_path / "review",
        seat_dir=tmp_path / "seat",
        image_sha256="1" * 64,
        admission_class="synthetic",
    )
    teardown: list[tuple[int, str]] = []
    retained: list[Path] = []
    boundaries: list[str] = []

    def teardown_in_h(pid: int, parent: str) -> list[str]:
        teardown.append((pid, parent))
        return [f"retained-{len(teardown)}"]

    monkeypatch.setattr(panel_invoker._seat_uid, "teardown_in_h", teardown_in_h)
    cleanup_failure = leg == "claude" and refusal == "source_changed"

    def record_retention(path: Path) -> None:
        retained.append(path)
        if cleanup_failure:
            raise RuntimeError("synthetic cleanup failure")

    monkeypatch.setattr(panel_invoker._seat_uid, "record_retention", record_retention)
    monkeypatch.setattr(
        panel_invoker,
        "_broker_claude_tui_command",
        lambda **_kwargs: ["/run/phase-loop-seat/provider"],
    )
    monkeypatch.setattr(
        panel_invoker,
        "_jailed_gemini_command",
        lambda _model: ["/run/phase-loop-seat/provider"],
    )
    monkeypatch.setattr(
        panel_invoker,
        "_run_claude_tui_session",
        lambda **_kwargs: boundaries.append("claude-provider") or pytest.fail("provider ran"),
    )
    monkeypatch.setattr(
        panel_invoker,
        "_run_leg_with_liveness",
        lambda *_args, **_kwargs: boundaries.append("gemini-provider") or pytest.fail("provider ran"),
    )
    for name in ("_require_qualified_jail", "_require_jailed_seat_identity", "launch_provider"):
        monkeypatch.setattr(
            panel_invoker,
            name,
            lambda *_args, _name=name, **_kwargs: boundaries.append(_name)
            or pytest.fail(f"{_name} boundary ran"),
        )

    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as excinfo:
            if leg == "claude":
                panel_invoker._exec_jailed_claude_leg(
                    seat,
                    timeout_s=5,
                    backstop_s=5,
                    model=None,
                    effort=None,
                    prompt="synthetic",
                    broker_evidence={},
                )
            else:
                panel_invoker._exec_jailed_gemini_leg(
                    seat,
                    deadline_s=5,
                    model="synthetic-model",
                    prompt="synthetic",
                    broker_evidence={},
                )
        assert excinfo.value.code == seat_jail.refused("identity")
        if refusal == "source_changed":
            assert isinstance(excinfo.value.__cause__, ExecutableDependencyError)
        assert boundaries == []
        assert [parent for _pid, parent in teardown] == [
            str(seat.review_dir),
            str(seat.seat_dir),
            str(seat.seat_dir / panel_invoker._JAIL_PROBE_DIRNAME),
        ]
        assert len(retained) == 3
        assert seat.notices == ["seat_sandbox_retained_after_teardown"]
        if cleanup_failure:
            assert len(excinfo.value.__notes__) == 3
            assert all("cleanup also failed" in note for note in excinfo.value.__notes__)
        _assert_descriptors_closed(descriptors)
    finally:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass


@pytest.mark.parametrize(
    "collision",
    [
        "review_tree",
        "readonly_ca",
        "writable_tree",
        "output",
        "broker",
        "keyring",
        "private_home",
        "system",
    ],
)
def test_generic_profile_refuses_dependency_collision_before_reopen_or_effects(
    collision: str,
) -> None:
    base = Path("/synthetic-seat-view")
    cwd = base / "review" / "tree"
    readonly = Path("/etc/ssl/certs/ca-certificates.crt")
    writable = base / "writable-tree"
    output = base / "output" / "review.txt"
    broker = Path("/run/user/123/synthetic-broker.sock")
    destinations = {
        "review_tree": str(cwd / "provider"),
        "readonly_ca": str(readonly),
        "writable_tree": str(writable / "provider"),
        "output": str(output),
        "broker": str(broker),
        "keyring": "/run/phase-loop-seat/keyring.py",
        "private_home": "/home/phase-loop-seat/.config/provider",
        "system": "/usr/lib/synthetic-provider",
    }
    effects: list[str] = []

    class Dependency:
        subject_destination = "/fixture/provider"
        entries = (SimpleNamespace(destination=destinations[collision]),)

        def revalidate(self) -> None:
            effects.append("revalidate")

        def reopen_projection(self):
            effects.append("reopen")
            raise AssertionError("projection reopened")

    with pytest.raises(
        panel_invoker._sandbox_egress.SeatIdentityUnverified,
        match="seat_profile_unavailable",
    ):
        with panel_invoker.seat_profile(
            harness=None,
            executable="/usr/bin/true",
            env={},
            cwd=cwd,
            readonly_paths=(readonly,),
            outputs=(output,),
            broker_socket=broker,
            writable_trees=(writable,),
            dependency=Dependency(),
        ):
            pytest.fail("colliding projection reached the seat profile")
    assert effects == []


def test_generic_profile_allows_only_the_exact_provider_subject_slot(tmp_path: Path) -> None:
    dependency = SimpleNamespace(
        subject_destination="/run/phase-loop-seat/provider",
        entries=(SimpleNamespace(destination="/run/phase-loop-seat/provider"),),
    )
    panel_invoker._require_safe_dependency_profile_destinations(
        dependency,
        cwd=tmp_path,
        private_home="/home/phase-loop-seat",
    )
    dependency.entries = (SimpleNamespace(destination="/run/phase-loop-seat/provider/helper"),)
    with pytest.raises(panel_invoker._sandbox_egress.SeatIdentityUnverified):
        panel_invoker._require_safe_dependency_profile_destinations(
            dependency,
            cwd=tmp_path,
            private_home="/home/phase-loop-seat",
        )


def test_owned_launch_rechecks_output_directory_collision_before_any_owner_effect(
    monkeypatch,
    tmp_path: Path,
) -> None:
    effects: list[str] = []
    output_directory = Path("/synthetic-seat-view/private-output")

    class Dependency:
        subject_destination = "/fixture/provider"
        projection_digest = "a" * 64
        entries = (SimpleNamespace(destination=str(output_directory / "helper")),)

        def revalidate(self) -> None:
            effects.append("revalidate")

    profile = panel_invoker.SeatProfile(
        env={"HOME": "/home/phase-loop-seat"},
        dependency=Dependency(),
        dependency_projection_digest="a" * 64,
        output_dirs=((str(tmp_path / "host-output"), str(output_directory)),),
    )
    monkeypatch.setattr(
        panel_invoker,
        "_filtered_holder_namespace",
        lambda: effects.append("namespace"),
    )
    monkeypatch.setattr(
        panel_invoker,
        "launch_provider",
        lambda *_args, **_kwargs: effects.append("provider"),
    )
    with pytest.raises(panel_invoker._sandbox_egress.SeatIdentityUnverified):
        panel_invoker.launch_owned(
            ["/fixture/provider"],
            role=panel_invoker.SeatLaunchRole.PROVIDER_REVIEW,
            profile=profile,
            cwd=tmp_path,
        )
    assert effects == []


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
