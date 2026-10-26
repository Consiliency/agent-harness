from __future__ import annotations

import os
from pathlib import Path

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime.executable_dependency import ExecutableDependencyError, admit_executable_dependency
from phase_loop_runtime import panel_invoker, seat_jail


def _review_dir(root: Path) -> Path:
    review = root
    (review / seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True, mode=0o700)
    return review


def _build(review: Path, subject: Path, dependency):
    bundle = seat_jail.memfd_with("synthetic-bundle", b"bundle")
    instructions = seat_jail.memfd_with("synthetic-instructions", b"instructions")
    token = seat_jail.token_pipe(b"synthetic-token")
    try:
        return seat_jail.build_seat_jail(
            "claude",
            review,
            subject,
            bundle_memfd=bundle,
            instructions_memfd=instructions,
            token_fd=token,
            seat_ids=(1, 1),
            dependency=dependency,
        )
    except BaseException:
        for fd in (bundle, instructions, token):
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def test_production_and_probe_reopen_same_projection_with_independent_fds(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture", layout="layout-b")
    try:
        dependency = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        production = probe = None
        try:
            production = _build(_review_dir(tmp_path / "production"), fixture.subject, dependency)
            probe = _build(_review_dir(tmp_path / "probe"), fixture.subject, dependency)
            assert production.dependency_projection_digest == dependency.projection_digest
            assert probe.dependency_projection_digest == dependency.projection_digest
            assert set(production.dependency_fds).isdisjoint(probe.dependency_fds)
            assert seat_jail.actual_profile_digest(production) == seat_jail.jail_profile_digest("claude")
            assert seat_jail.actual_profile_digest(probe) == seat_jail.jail_profile_digest("claude")
            assert set(production.dependency_destinations) == set(probe.dependency_destinations)
            assert {str(fixture.subject_destination), str(fixture.helper_destination)} <= set(
                seat_jail.expected_mount_points(production)
            )
            assert fixture.authority_fd not in production.pass_fds
            assert fixture.authority_fd not in probe.pass_fds
        finally:
            if probe is not None:
                seat_jail.close_jail_fds(probe)
            if production is not None:
                seat_jail.close_jail_fds(production)
            dependency.close()
    finally:
        fixture.close()


def test_mutation_refuses_before_jail_directories_are_created(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture")
    try:
        dependency = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        try:
            fixture.helper.write_bytes(b"mutated")
            review = _review_dir(tmp_path / "refused")
            with pytest.raises(ExecutableDependencyError, match="source_changed"):
                _build(review, fixture.subject, dependency)
            assert not (review / seat_jail.HOST_HOME_DIRNAME).exists()
            assert not (review / seat_jail.HOST_OUT_DIRNAME).exists()
        finally:
            dependency.close()
    finally:
        fixture.close()


def test_mutation_immediately_before_launch_never_reaches_process_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path / "fixture")
    launched: list[object] = []
    try:
        dependency = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        production = probe = None
        try:
            production = _build(_review_dir(tmp_path / "production"), fixture.subject, dependency)
            probe = _build(_review_dir(tmp_path / "probe"), fixture.subject, dependency)
            monkeypatch.setattr(
                panel_invoker.subprocess,
                "Popen",
                lambda *_args, **_kwargs: launched.append(object()),
            )
            egress = panel_invoker._EGRESS_LAUNCH_PREFIX.set(
                ("/usr/bin/nsenter", "--net=/proc/1/ns/net", "/usr/bin/setpriv", "--")
            )
            try:
                fixture.helper.write_bytes(b"changed-before-launch")
                with pytest.raises(ExecutableDependencyError, match="source_changed"):
                    panel_invoker.launch_provider(
                        [production.provider_argv0],
                        process_owner=production,
                        probe_owner=probe,
                        env={},
                    )
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(egress)
            assert not launched
        finally:
            if probe is not None:
                seat_jail.close_jail_fds(probe)
            if production is not None:
                seat_jail.close_jail_fds(production)
            dependency.close()
    finally:
        fixture.close()
