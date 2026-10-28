from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest
import rfc8785

from executable_dependency_test_support import build_fixture
from phase_loop_runtime.executable_dependency import (
    AdmittedExecutableDependency,
    ExecutableDependencyError,
    ProjectionPolicy,
    _parse_canonical,
    admit_executable_dependency,
)


@pytest.mark.parametrize("layout", ("layout-a", "layout-b"))
def test_admits_two_neutral_layouts_and_holds_cloexec_descriptors(tmp_path: Path, layout: str) -> None:
    fixture = build_fixture(tmp_path / layout, layout=layout)
    try:
        admitted = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        try:
            assert admitted.subject_source == str(fixture.subject)
            assert admitted.subject_destination == str(fixture.subject_destination)
            assert admitted.projection_digest
            admitted.revalidate()
            with pytest.raises(ExecutableDependencyError, match="subject_mismatch"):
                admitted.validate_command(["/bin/sh"], provider="synthetic")
            projection = admitted.reopen_projection()
            try:
                assert projection.digest == admitted.projection_digest
                assert len(projection.pass_fds) == 2
                assert len(set(projection.pass_fds)) == 2
                assert all(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC for fd in projection.pass_fds)
                mount_args = projection.mount_args()
                assert "--ro-bind-data" in mount_args
                if layout == "layout-b":
                    assert "--symlink" in mount_args
            finally:
                fds = projection.pass_fds
                projection.close()
                for fd in fds:
                    with pytest.raises(OSError):
                        os.fstat(fd)
            subject_fd = admitted.reopen_subject()
            try:
                seals = fcntl.fcntl(subject_fd, getattr(fcntl, "F_GET_SEALS", 1034))
                assert seals & 0xF == 0xF
                assert os.read(subject_fd, fixture.subject.stat().st_size) == fixture.subject.read_bytes()
            finally:
                os.close(subject_fd)
        finally:
            admitted.close()
        # Public admission borrows but never closes the private caller's descriptor.
        os.fstat(fixture.authority_fd)
    finally:
        fixture.close()


def test_source_mutation_is_refused_on_lifecycle_revalidation(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "mutation")
    try:
        admitted = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        try:
            fixture.helper.write_bytes(b"changed")
            with pytest.raises(ExecutableDependencyError, match="source_changed"):
                admitted.revalidate()
        finally:
            admitted.close()
    finally:
        fixture.close()


def test_command_path_must_still_name_the_held_subject_inode(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "ancestor-swap")
    try:
        admitted = admit_executable_dependency(
            fixture.requirement,
            fixture.authority_fd,
            fixture.requirement.expected_authority_sha256,
        )
        try:
            original = fixture.subject.read_bytes()
            moved = fixture.release.with_name(fixture.release.name + "-held")
            fixture.release.rename(moved)
            fixture.subject.parent.mkdir(parents=True)
            fixture.subject.write_bytes(original)
            fixture.subject.chmod(0o755)
            with pytest.raises(ExecutableDependencyError, match="source_changed"):
                admitted.validate_command([str(fixture.subject)], provider="synthetic")
        finally:
            admitted.close()
    finally:
        fixture.close()


@pytest.mark.parametrize(
    "transform",
    (
        lambda authority: {**authority, "unknown": True},
        lambda authority: {**authority, "authority_version": True},
        lambda authority: json.dumps(
            {
                **authority,
                "source_roots": [
                    {**authority["source_roots"][0], "device": 9_007_199_254_740_992}
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii"),
        lambda authority: b'{"authority_version":1,"authority_version":1}',
        lambda authority: __import__("rfc8785").dumps(authority) + b"\n",
    ),
    ids=("unknown-field", "bool-integer", "safe-max-plus-one", "duplicate-key", "trailing-newline"),
)
def test_closed_canonical_authority_failures_precede_effects(tmp_path: Path, transform) -> None:
    fixture = build_fixture(tmp_path / "invalid", authority_transform=transform)
    try:
        with pytest.raises(ExecutableDependencyError, match="authority_invalid"):
            admit_executable_dependency(
                fixture.requirement,
                fixture.authority_fd,
                fixture.requirement.expected_authority_sha256,
            )
        os.fstat(fixture.authority_fd)
    finally:
        fixture.close()


def test_each_policy_layer_can_narrow_destination_roots(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "policy")
    try:
        denied = ProjectionPolicy(allowed_roots=("/srv/another-runtime",))
        with pytest.raises(ExecutableDependencyError, match="destination policy intersection"):
            admit_executable_dependency(
                fixture.requirement,
                fixture.authority_fd,
                fixture.requirement.expected_authority_sha256,
                host_policy=denied,
            )
    finally:
        fixture.close()


@pytest.mark.parametrize(
    "fixture_kwargs",
    (
        {"helper_mode": 0o664},
        {"directory_mode": 0o775},
    ),
    ids=("group-writable-file", "group-writable-directory-and-source-root"),
)
def test_public_mode_floor_rejects_group_or_world_writable_sources(
    tmp_path: Path,
    fixture_kwargs,
) -> None:
    fixture = build_fixture(tmp_path / "writable", **fixture_kwargs)
    try:
        with pytest.raises(ExecutableDependencyError, match="authority_invalid"):
            admit_executable_dependency(
                fixture.requirement,
                fixture.authority_fd,
                fixture.requirement.expected_authority_sha256,
                public_policy=ProjectionPolicy(
                    file_modes=frozenset({"0644", "0664", "0755"}),
                    directory_modes=frozenset({"0755", "0775"}),
                ),
            )
    finally:
        fixture.close()


def test_final_admission_revalidation_failure_closes_every_owned_descriptor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path / "final-revalidation")
    before = set(os.listdir("/proc/self/fd"))

    def refuse_final_revalidation(_dependency) -> None:
        raise ExecutableDependencyError("source_changed", "final")

    monkeypatch.setattr(
        AdmittedExecutableDependency,
        "revalidate",
        refuse_final_revalidation,
    )
    try:
        with pytest.raises(ExecutableDependencyError, match="source_changed"):
            admit_executable_dependency(
                fixture.requirement,
                fixture.authority_fd,
                fixture.requirement.expected_authority_sha256,
            )
        assert set(os.listdir("/proc/self/fd")) == before
    finally:
        fixture.close()


def test_safe_integer_maximum_round_trips_exactly(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "safe-max")
    try:
        authority = json.loads(rfc8785.dumps(fixture.authority))
        authority["source_roots"][0]["device"] = 9_007_199_254_740_991
        unsigned = dict(authority)
        unsigned.pop("authority_id")
        authority["authority_id"] = hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest()
        parsed = _parse_canonical(
            rfc8785.dumps(authority),
            "executable-dependency-authority-v1.schema.json",
        )
        assert parsed["source_roots"][0]["device"] == 9_007_199_254_740_991
    finally:
        fixture.close()


def test_public_fixture_bytes_are_canonical_and_hash_bound() -> None:
    root = Path(__file__).parent / "fixtures/executable_dependency"
    for layout in ("layout-a", "layout-b"):
        directory = root / layout
        expected = {
            line.split()[1]: line.split()[0]
            for line in (directory / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        }
        for name, digest in expected.items():
            raw = (directory / name).read_bytes()
            assert not raw.endswith(b"\n")
            assert hashlib.sha256(raw).hexdigest() == digest
            assert rfc8785.dumps(json.loads(raw)) == raw
