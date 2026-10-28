from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

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


def _projection_file_descriptors(jail) -> dict[str, int]:
    args = jail.dependency_mount_args
    files: dict[str, int] = {}
    for index, item in enumerate(args):
        if item == "--ro-bind-data":
            files[args[index + 2]] = int(args[index + 1])
    return files


def _read_all(fd: int, chunk_size: int = 2) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(fd, chunk_size):
        chunks.append(chunk)
    return b"".join(chunks)


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
            evidence: dict[str, object] = {}
            panel_invoker._record_executable_dependency_evidence(evidence, production)
            assert evidence == {
                "executable_dependency_projection_sha256": dependency.projection_digest,
                "executable_dependency_authority_sha256": dependency.authority_sha256,
                "executable_dependency_declaration_sha256": dependency.declaration_sha256,
                "executable_dependency_runtime_euid_owned_sources": True,
                "executable_dependency_runtime_euid_writable_sources": True,
            }
            expected = {
                str(fixture.subject_destination): fixture.subject.read_bytes(),
                str(fixture.helper_destination): fixture.helper.read_bytes(),
            }
            probe_files = _projection_file_descriptors(probe)
            production_files = _projection_file_descriptors(production)
            assert probe_files.keys() == production_files.keys() == expected.keys()

            # A real sequential consumer drains every probe descriptor. Production
            # descriptors must still begin at byte zero.
            for destination, descriptor in probe_files.items():
                observed = _read_all(descriptor)
                assert observed == expected[destination]
                assert hashlib.sha256(observed).digest() == hashlib.sha256(
                    expected[destination]
                ).digest()
            assert all(os.lseek(fd, 0, os.SEEK_CUR) == 0 for fd in production_files.values())

            # Read production and a later consumer interleaved. Independent FD
            # numbers alone would not make this pass if they shared an OFD offset.
            with dependency.reopen_projection() as subsequent:
                subsequent_files = {
                    item.destination: item.fd for item in subsequent.files
                }
                assert subsequent_files.keys() == production_files.keys()
                for destination in expected:
                    production_bytes = bytearray()
                    subsequent_bytes = bytearray()
                    while True:
                        left = os.read(production_files[destination], 1)
                        right = os.read(subsequent_files[destination], 3)
                        production_bytes.extend(left)
                        subsequent_bytes.extend(right)
                        if not left and not right:
                            break
                    assert bytes(production_bytes) == expected[destination]
                    assert bytes(subsequent_bytes) == expected[destination]
                    expected_digest = hashlib.sha256(expected[destination]).digest()
                    assert hashlib.sha256(production_bytes).digest() == expected_digest
                    assert hashlib.sha256(subsequent_bytes).digest() == expected_digest
        finally:
            if probe is not None:
                seat_jail.close_jail_fds(probe)
            if production is not None:
                seat_jail.close_jail_fds(production)
            dependency.close()
    finally:
        fixture.close()


@pytest.mark.parametrize(
    "destination",
    (
        "/seat",
        "/seat/review/review-bundle.md",
        "/seat/tree/injected",
        "/seat/home",
        "/seat/out/result",
        "/seat/egress-ca.pem",
        "/usr",
        "/usr/bin/injected",
        "/etc/ssl",
        "/proc/self/status",
    ),
)
def test_dependency_destination_overlap_refuses_before_jail_effects(
    tmp_path: Path,
    destination: str,
) -> None:
    effects: list[str] = []
    dependency = SimpleNamespace(
        entries=(SimpleNamespace(destination=destination),),
        subject_destination="/fixture/provider",
        revalidate=lambda: effects.append("revalidate"),
    )
    review = _review_dir(tmp_path / destination.strip("/").replace("/", "-"))
    with pytest.raises(seat_jail.SeatSandboxRefused, match="dependency destination overlaps"):
        _build(review, Path("/unused/provider"), dependency)
    assert effects == []
    assert not (review / seat_jail.HOST_HOME_DIRNAME).exists()
    assert not (review / seat_jail.HOST_OUT_DIRNAME).exists()


def test_only_exact_provider_subject_gets_narrow_seat_bin_exception() -> None:
    seat_jail._require_safe_dependency_destinations(
        "claude",
        ("/seat/bin/claude",),
        "/seat/bin/claude",
    )
    with pytest.raises(seat_jail.SeatSandboxRefused, match="dependency destination overlaps"):
        seat_jail._require_safe_dependency_destinations(
            "claude",
            ("/seat/bin/claude", "/seat/bin/claude-helper"),
            "/seat/bin/claude",
        )


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
