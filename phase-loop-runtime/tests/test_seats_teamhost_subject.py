from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

import pytest
import rfc8785

from phase_loop_runtime import panel_invoker
from phase_loop_runtime import executor_availability
from phase_loop_runtime import seat_subject
from phase_loop_runtime.executable_dependency import ExecutableDependencyError


AUTHORITY_ID = "a" * 64
BASE_PROFILE = "b" * 64
AUTHORITY_SHA256 = "c" * 64


def _exe(path: Path, data: bytes = b"\x7fELFmanaged", mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


@pytest.fixture(autouse=True)
def _fixed_umask():
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def managed_fs(tmp_path, monkeypatch):
    root = tmp_path / "root"
    releases = root / "opt/consiliency/tooling/releases"
    pin = root / "etc/consiliency/tooling/seat-authority.json"
    releases.mkdir(parents=True)
    pin.parent.mkdir(parents=True)
    for path in (root, *root.rglob("*")):
        if path.is_dir():
            path.chmod(0o755)
    owners = frozenset({0, os.geteuid()})
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", releases)
    monkeypatch.setattr(seat_subject, "MANAGED_AUTHORITY_PIN", pin)
    monkeypatch.setattr(seat_subject, "_PIN_WALK_ROOT", root)
    monkeypatch.setattr(seat_subject, "_PIN_OWNERS", owners)
    monkeypatch.setattr(seat_subject, "_MANAGED_OWNERS", owners)
    monkeypatch.setattr(panel_invoker, "_FRONTDOOR_RELEASES", releases)
    monkeypatch.setattr(panel_invoker, "_FRONTDOOR_OWNERS", owners)
    monkeypatch.setattr(seat_subject, "_current_dependency", lambda _leg: None)
    return root, releases, pin


def _release(releases: Path, release_id: str = "2026.11.06-teamhost.1") -> tuple[Path, Path]:
    release = releases / release_id
    _exe(release / "source/lib/user_agent_tools.py", b"# launcher\n", 0o644)
    (release / "node/bin").mkdir(parents=True)
    native = _exe(release / "native/claude")
    for path in (release, *release.rglob("*")):
        if path.is_dir():
            path.chmod(0o755)
    return release, native


def _frontdoor(bin_dir: Path, release: Path, native: Path, *, extra: str = "") -> Path:
    return _exe(
        bin_dir / "claude",
        (
            "#!/bin/sh\n"
            f'export PATH={release}/node/bin:"$PATH"\n'
            "export DISABLE_AUTOUPDATER=1\n"
            f"exec /usr/bin/python3 -I {release}/source/lib/user_agent_tools.py launch"
            f" --provider claude --shared {native}{extra}"
            f' --node-bin {release}/node/bin -- "$@"\n'
        ).encode(),
    )


def _pin(pin: Path, release_id: str, entry=None) -> None:
    if entry is None:
        entry = {
            "authority_sha256": AUTHORITY_SHA256,
            "authority_id": AUTHORITY_ID,
            "base_profile_sha256": BASE_PROFILE,
        }
    pin.write_bytes(
        rfc8785.dumps(
            {
                "schema": "seat_authority_pin.v2",
                "releases": {release_id: {"claude": entry}},
            }
        )
    )
    pin.chmod(0o644)


def _resolve(bin_dir: Path):
    return seat_subject.resolve_seat_subject("claude", {"PATH": str(bin_dir)})


def test_bound_session_lease_wins_without_path_lookup(monkeypatch):
    dependency = object()
    monkeypatch.setattr(seat_subject, "_current_dependency", lambda leg: dependency)
    monkeypatch.setattr(
        seat_subject.shutil,
        "which",
        lambda *_args, **_kwargs: pytest.fail("PATH lookup after a bound lease"),
    )
    assert seat_subject.resolve_seat_subject("claude", {"PATH": ""}) == seat_subject.SeatSubject(
        "claude", "session_lease", None, None, None
    )


def test_guarded_frontdoor_builds_requirement_only_from_selected_subject_and_pin(
    managed_fs, tmp_path
):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    _pin(pin, release.name)

    subject = _resolve(door.parent)

    assert subject.source == "managed_release"
    assert subject.subject_path == native
    assert subject.release_id == release.name
    assert subject.requirement is not None
    assert subject.requirement.provider == "claude"
    assert subject.requirement.authority_id == AUTHORITY_ID
    assert subject.requirement.expected_authority_sha256 == AUTHORITY_SHA256
    assert subject.requirement.base_profile_sha256 == BASE_PROFILE
    assert subject.requirement.selected_executable.path == str(native)
    assert subject.requirement.selected_executable.sha256 == hashlib.sha256(native.read_bytes()).hexdigest()
    assert str(release / "source/lib/user_agent_tools.py") not in repr(subject.requirement)


def test_plain_path_install_is_standalone_and_path_is_read_at_call_time(
    managed_fs, tmp_path
):
    _root, _releases, _pin_path = managed_fs
    first = _exe(tmp_path / "one/claude", b"first")
    second = _exe(tmp_path / "two/claude", b"second")

    one = seat_subject.resolve_seat_subject("claude", {"PATH": str(first.parent)})
    two = seat_subject.resolve_seat_subject("claude", {"PATH": str(second.parent)})

    assert (one.source, one.subject_path) == ("standalone", first)
    assert (two.source, two.subject_path) == ("standalone", second)


def test_managed_release_missing_pin_or_entry_never_falls_back(managed_fs, tmp_path):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)

    with pytest.raises(ExecutableDependencyError) as missing:
        _resolve(door.parent)
    assert missing.value.code == "authority_missing"

    pin.write_bytes(rfc8785.dumps({"schema": "seat_authority_pin.v2", "releases": {}}))
    pin.chmod(0o644)
    with pytest.raises(ExecutableDependencyError) as absent:
        _resolve(door.parent)
    assert absent.value.code == "authority_missing"


@pytest.mark.parametrize(
    "entry",
    [
        {"authority_sha256": AUTHORITY_SHA256, "authority_id": AUTHORITY_ID},
        {
            "authority_sha256": "not-a-digest",
            "authority_id": AUTHORITY_ID,
            "base_profile_sha256": BASE_PROFILE,
        },
    ],
)
def test_malformed_v2_pin_entry_refuses_authority_invalid(managed_fs, tmp_path, entry):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    _pin(pin, release.name, entry)

    with pytest.raises(ExecutableDependencyError) as refused:
        _resolve(door.parent)
    assert refused.value.code == "authority_invalid"


def test_unsafe_pin_file_or_ancestor_refuses_authority_invalid(managed_fs, tmp_path):
    root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    _pin(pin, release.name)

    pin.chmod(0o666)
    with pytest.raises(ExecutableDependencyError) as writable:
        _resolve(door.parent)
    assert writable.value.code == "authority_invalid"

    pin.chmod(0o644)
    (root / "etc").chmod(0o777)
    with pytest.raises(ExecutableDependencyError) as ancestor:
        _resolve(door.parent)
    assert ancestor.value.code == "authority_invalid"


def test_unrecognised_guarded_frontdoor_never_launches_as_standalone(managed_fs, tmp_path):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native, extra=" --new-flag")
    _pin(pin, release.name)

    with pytest.raises(ExecutableDependencyError) as refused:
        _resolve(door.parent)
    assert refused.value.code == "subject_mismatch"


def test_open_managed_authority_checks_the_independent_digest(managed_fs, tmp_path):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    authority = release / "share/phase-loop/seat-dependencies/claude/authority.json"
    authority_bytes = b"pinned authority bytes"
    _exe(authority, authority_bytes, 0o644)
    expected = hashlib.sha256(authority_bytes).hexdigest()
    _pin(
        pin,
        release.name,
        {
            "authority_sha256": expected,
            "authority_id": AUTHORITY_ID,
            "base_profile_sha256": BASE_PROFILE,
        },
    )
    subject = _resolve(door.parent)

    descriptor, digest = seat_subject.open_managed_authority(subject)
    try:
        assert digest == expected
        assert os.read(descriptor, len(authority_bytes)) == authority_bytes
    finally:
        os.close(descriptor)

    authority.write_bytes(b"changed authority bytes")
    authority.chmod(0o644)
    with pytest.raises(ExecutableDependencyError) as refused:
        seat_subject.open_managed_authority(subject)
    assert refused.value.code == "authority_invalid"


@pytest.mark.parametrize(
    "kind,path_parts,installer",
    [
        ("uv_tool", ("uv", "tools", "phase-loop-runtime", "lib", "phase_loop_runtime.py"), None),
        ("pip", ("installed", "phase_loop_runtime", "seat_subject.py"), "pip"),
        ("unknown", ("installed", "phase_loop_runtime", "seat_subject.py"), "uv"),
    ],
)
def test_deployment_kind_uses_paths_and_installer_without_spawning(
    tmp_path, monkeypatch, kind, path_parts, installer
):
    package = tmp_path.joinpath(*path_parts)
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text("x")
    monkeypatch.setattr(seat_subject, "_runtime_package_path", lambda: package)
    monkeypatch.setattr(seat_subject, "_distribution_installer", lambda: installer)
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", tmp_path / "releases")
    assert seat_subject.deployment_kind() == kind


def test_deployment_kind_managed_and_source(tmp_path, monkeypatch):
    managed = tmp_path / "releases/r1/src/phase_loop_runtime/seat_subject.py"
    managed.parent.mkdir(parents=True)
    managed.write_text("x")
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", tmp_path / "releases")
    monkeypatch.setattr(seat_subject, "_runtime_package_path", lambda: managed)
    assert seat_subject.deployment_kind() == "managed"

    project = tmp_path / "checkout/phase-loop-runtime"
    package = project / "src/phase_loop_runtime/seat_subject.py"
    package.parent.mkdir(parents=True)
    package.write_text("x")
    (project / "pyproject.toml").write_text("[project]\nname='phase-loop-runtime'\n")
    monkeypatch.setattr(seat_subject, "_runtime_package_path", lambda: package)
    monkeypatch.setattr(seat_subject, "_distribution_installer", lambda: "pip")
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", tmp_path / "other-releases")
    assert seat_subject.deployment_kind() == "source"


def test_register_provider_executable_is_idempotent_and_rejects_conflict(monkeypatch):
    monkeypatch.setitem(seat_subject._PROVIDER_EXECUTABLES, "future", "future")
    seat_subject.register_provider_executable("future", "future")
    with pytest.raises(ValueError, match="already registered"):
        seat_subject.register_provider_executable("future", "different")


def test_search_only_ancestor_reaches_the_real_auth_probe(tmp_path, monkeypatch):
    assert os.geteuid() != 0, "root would make the search-only proof vacuous"
    gate = tmp_path / "gate"
    work = gate / "operator/work"
    work.mkdir(parents=True)
    cli = _exe(work / "stub-cli", b"#!/bin/sh\nexit 0\n")
    monkeypatch.chdir(work)
    monkeypatch.setenv("TMPDIR", str(work))
    monkeypatch.setenv("PATH", f"{cli.parent}:/usr/bin:/bin")
    monkeypatch.setattr(tempfile, "tempdir", None)
    executor_availability.clear_auth_cache()
    gate.chmod(0o111)
    try:
        probes = (f"{cli} --version",)
        assert executor_availability.auth_ok_for(
            "future", probes, now=0.0) is True, executor_availability.auth_refusal_for(
                "future", probes)
    finally:
        gate.chmod(0o755)
        executor_availability.clear_auth_cache()
