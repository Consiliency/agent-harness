from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

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


def _frontdoor(
    bin_dir: Path, release: Path, native: Path, *, extra: str = "", leg: str = "claude",
) -> Path:
    return _exe(
        bin_dir / leg,
        (
            "#!/bin/sh\n"
            f'export PATH={release}/node/bin:"$PATH"\n'
            "export DISABLE_AUTOUPDATER=1\n"
            f"exec /usr/bin/python3 -I {release}/source/lib/user_agent_tools.py launch"
            f" --provider {leg} --shared {native}{extra}"
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


def test_relative_and_empty_path_entries_are_ignored(managed_fs, tmp_path, monkeypatch):
    _root, _releases, _pin_path = managed_fs
    work = tmp_path / "work"
    work.mkdir()
    _exe(work / "claude", b"cwd-provider")
    absolute = _exe(tmp_path / "trusted/claude", b"absolute-provider")
    monkeypatch.chdir(work)

    subject = seat_subject.resolve_seat_subject(
        "claude", {"PATH": os.pathsep.join(("", ".", "relative", str(absolute.parent)))}
    )

    assert (subject.source, subject.subject_path) == ("standalone", absolute)
    with pytest.raises(FileNotFoundError, match="seat_provider_unavailable"):
        seat_subject.resolve_seat_subject("claude", {"PATH": os.pathsep.join(("", ".", "relative"))})


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


def test_versioned_install_reached_through_a_link_stays_standalone(managed_fs, tmp_path):
    real = _exe(tmp_path / "versions/2.1.33")
    link = tmp_path / "bin/claude"
    link.parent.mkdir()
    link.symlink_to(real)

    subject = _resolve(link.parent)

    assert (subject.source, subject.subject_path) == ("standalone", real)


@pytest.mark.parametrize("shape", ["extra-line", "foreign-shape", "bad-export"])
def test_frontdoor_that_fails_a_shape_check_refuses(managed_fs, tmp_path, shape):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    _pin(pin, release.name)
    lines = door.read_text().splitlines()
    if shape == "extra-line":
        lines.insert(1, "/usr/bin/true --arbitrary")
    elif shape == "bad-export":
        lines[1] = "export FLAG='two words'"
    else:
        lines[-1] = 'exec /usr/bin/python3 -I /elsewhere/tool.py launch "$@"'
    door.write_text("\n".join(lines) + "\n")

    with pytest.raises(ExecutableDependencyError) as refused:
        _resolve(door.parent)
    assert refused.value.code == "subject_mismatch"


@pytest.mark.parametrize("wrapper", ["group-writable", "other-line", "dangling", "five-hops"])
def test_wrapper_into_the_release_tree_never_resolves_standalone(managed_fs, tmp_path, wrapper):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    _pin(pin, release.name)
    mode = 0o775 if wrapper == "group-writable" else 0o755
    body = f'#!/bin/sh\nexec {native} "$@"\n'
    if wrapper == "other-line":
        body = f'#!/bin/sh\numask 022\nexec {native} "$@"\n'
    elif wrapper == "dangling":
        body = f'#!/bin/sh\nexec {release}/native/absent "$@"\n'
    door = _exe(tmp_path / "bin/claude", body.encode(), mode)
    if wrapper == "five-hops":
        target = native
        for hop in range(5, 0, -1):
            target = _exe(tmp_path / f"hop{hop}/claude", f'#!/bin/sh\nexec {target} "$@"\n'.encode())
        door = target

    with pytest.raises(ExecutableDependencyError) as refused:
        _resolve(door.parent)
    assert refused.value.code == "subject_mismatch"


def test_release_value_that_is_not_an_object_refuses_authority_invalid(managed_fs, tmp_path):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    pin.write_bytes(rfc8785.dumps({"schema": "seat_authority_pin.v2", "releases": {release.name: "x"}}))
    pin.chmod(0o644)

    with pytest.raises(ExecutableDependencyError) as refused:
        _resolve(door.parent)
    assert refused.value.code == "authority_invalid"


def test_authority_that_carries_its_own_digest_is_not_admitted_without_the_pin(managed_fs, tmp_path):
    _root, releases, pin = managed_fs
    release, native = _release(releases)
    door = _frontdoor(tmp_path / "bin", release, native)
    authority = release / "share/phase-loop/seat-dependencies/claude/authority.json"
    payload = b'{"self":"' + hashlib.sha256(b"self").hexdigest().encode() + b'"}'
    _exe(authority, payload, 0o644)
    _pin(pin, release.name)
    subject = _resolve(door.parent)

    with pytest.raises(ExecutableDependencyError) as refused:
        seat_subject.open_managed_authority(subject)
    assert refused.value.code == "authority_invalid"


def test_gemini_frontdoor_selects_the_native_agy_target(managed_fs, tmp_path):
    _root, releases, pin = managed_fs
    release, _native = _release(releases)
    agy = _exe(release / "native/agy")
    door = _exe(
        tmp_path / "bin/agy",
        (
            "#!/bin/sh\n"
            f"exec /usr/bin/python3 -I {release}/source/lib/user_agent_tools.py launch"
            f" --provider gemini --shared {agy} --node-bin {release}/node/bin -- \"$@\"\n"
        ).encode(),
    )
    pin.write_bytes(rfc8785.dumps({
        "schema": "seat_authority_pin.v2",
        "releases": {release.name: {"gemini": {
            "authority_sha256": AUTHORITY_SHA256,
            "authority_id": AUTHORITY_ID,
            "base_profile_sha256": BASE_PROFILE,
        }}},
    }))
    pin.chmod(0o644)

    subject = seat_subject.resolve_seat_subject("gemini", {"PATH": str(door.parent)})

    assert (subject.source, subject.subject_path) == ("managed_release", agy)


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
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned"))
    monkeypatch.setattr(os, "posix_spawn", lambda *_a, **_k: pytest.fail("spawned"))
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
    cli = _exe(work / "stub-cli", b"#!/bin/sh\necho search-only-probe-ran\n")
    seen = []

    def runner(probe):
        done = executor_availability._run_probe(probe)
        seen.append(done.stdout)
        return done
    monkeypatch.chdir(work)
    monkeypatch.setenv("TMPDIR", str(work))
    monkeypatch.setenv("PATH", f"{cli.parent}:/usr/bin:/bin")
    monkeypatch.setattr(tempfile, "tempdir", None)
    executor_availability.clear_auth_cache()
    gate.chmod(0o111)
    try:
        probes = (f"{cli} --version",)
        assert executor_availability.auth_ok_for(
            "future", probes, now=0.0, runner=runner) is True, executor_availability.auth_refusal_for(
                "future", probes)
        assert "search-only-probe-ran" in "".join(seen)

        executor_availability.clear_auth_cache()
        with monkeypatch.context() as mutant:
            mutant.setattr(panel_invoker.os, "O_PATH", os.O_RDONLY)
            assert executor_availability.auth_ok_for(
                "future", probes, now=1.0, runner=runner
            ) is False
    finally:
        gate.chmod(0o755)
        executor_availability.clear_auth_cache()


@pytest.fixture(name="managed_grok", params=["image-pin-only", "also-v2-authority"])
def _managed_grok(request, managed_fs, monkeypatch):
    from executable_dependency_test_support import build_fixture
    from phase_loop_runtime import seat_profile_grok

    root, releases, authority_pin = managed_fs
    dependency = build_fixture(
        releases, provider="grok", subject_relative="native/grok",
        subject_bytes=b"\x7fELFmanaged-grok",
    )
    dependency.close()
    release, native = dependency.release, dependency.subject
    _exe(release / "source/lib/user_agent_tools.py", b"# launcher\n", 0o644)
    (release / "node/bin").mkdir(parents=True)
    door = _frontdoor(release / "bin", release, native, leg="grok")
    (root / "current").symlink_to(release, target_is_directory=True)
    assert (root / "current/bin/grok").resolve(strict=True) == door
    env = {"PATH": str(root / "current/bin")}
    digest = hashlib.sha256(native.read_bytes()).hexdigest()
    monkeypatch.setattr(seat_subject, "platform", SimpleNamespace(machine=lambda: "x86_64"))
    monkeypatch.setattr(seat_profile_grok, "JAIL_PROTECTION", {
        **seat_profile_grok.JAIL_PROTECTION,
        digest: seat_profile_grok.JAIL_PROTECTION[seat_profile_grok.GROK_1_0_92_SHA256],
    })
    pin = authority_pin.with_name("grok-subject-pin.json")
    monkeypatch.setattr(seat_subject, "GROK_SUBJECT_PIN", pin)
    entry = {"binary_sha256": digest, "platform": "linux-x64", "version": "1.0.92"}
    pin.write_bytes(rfc8785.dumps({
        "schema": "grok_subject_pin.v1", "releases": {release.name: entry},
    }))
    legs = {"claude": {
        "authority_sha256": AUTHORITY_SHA256,
        "authority_id": AUTHORITY_ID,
        "base_profile_sha256": BASE_PROFILE,
    }}
    if request.param == "also-v2-authority":
        requirement = dependency.requirement
        legs["grok"] = {
            "authority_sha256": requirement.expected_authority_sha256,
            "authority_id": requirement.authority_id,
            "base_profile_sha256": requirement.base_profile_sha256,
        }
        _exe(release / "share/phase-loop/seat-dependencies/grok/authority.json",
             dependency.authority_path.read_bytes(), 0o644)
    authority_pin.write_bytes(rfc8785.dumps({
        "schema": "seat_authority_pin.v2", "releases": {release.name: legs},
    }))
    return env, native, digest, pin


def test_managed_grok_subject_uses_exact_release_pin(managed_grok):
    env, native, digest, _pin_path = managed_grok
    try:
        subject = seat_subject.resolve_seat_subject("grok", env)
    except ExecutableDependencyError as exc:
        pytest.fail(f"managed Grok lookup refused: {exc.code}")
    assert (subject.source, subject.subject_path, subject.release_id, subject.requirement) == (
        "managed_image", native, native.parents[1].name, None,
    )
    assert subject.binary_sha256 == digest


def test_resolved_jail_subject_admits_managed_grok_without_projection(managed_grok, monkeypatch):
    monkeypatch.setattr(seat_subject, "open_managed_authority",
                        lambda *_: pytest.fail("opened a dependency authority"))
    env, native, digest, _pin_path = managed_grok
    try:
        subject, dependency = panel_invoker._resolved_jail_subject("grok", env)
    except ExecutableDependencyError as exc:
        pytest.fail(f"jailed subject refused: {exc.code}")
    assert dependency is None
    assert (subject.source, subject.subject_path, subject.binary_sha256) == (
        "managed_image", native, digest,
    )


def test_wrapped_grok_subject_admits_managed_image(managed_grok):
    from phase_loop_runtime import grok_jail_surface, seat_jail

    env, native, digest, _pin_path = managed_grok
    try:
        subject = grok_jail_surface.resolve_subject(env)
    except seat_jail.SeatSandboxRefused as exc:
        pytest.fail(f"wrapped Grok subject refused: {exc.code}")
    assert (subject.path, subject.sha256) == (str(native), digest)


def test_managed_grok_fingerprints_are_exactly_the_ts_erratum_8_pin():
    from phase_loop_runtime.seat_profile_grok import JAIL_PROTECTION

    assert set(JAIL_PROTECTION) == {
        "add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb",
    }


@pytest.mark.parametrize("managed_grok", ["also-v2-authority"], indirect=True)
def test_managed_grok_accepts_a_retained_approved_release_at_the_id_limit(managed_grok):
    env, native, digest, pin = managed_grok
    doc = json.loads(pin.read_bytes())
    entry = doc["releases"][native.parents[1].name]
    doc["releases"]["a" * 255] = dict(entry)
    pin.write_bytes(rfc8785.dumps(doc))
    assert seat_subject.resolve_seat_subject("grok", env).binary_sha256 == digest


@pytest.mark.parametrize("managed_grok", ["also-v2-authority"], indirect=True)
@pytest.mark.parametrize(("change", "code"), [
    ("missing", "authority_missing"),
    ("other-release", "authority_missing"),
    ("noncanonical", "authority_invalid"),
    ("duplicate", "authority_invalid"),
    ("extra-field", "authority_invalid"),
    ("unsafe-release", "authority_invalid"),
    ("plus-release", "authority_invalid"),
    ("at-release", "authority_invalid"),
    ("dash-leading-release", "authority_invalid"),
    ("dot-leading-release", "authority_invalid"),
    ("long-release", "authority_invalid"),
    ("unselected-unapproved", "authority_invalid"),
    ("wrong-version", "authority_invalid"),
    ("wrong-platform", "authority_invalid"),
    ("wrong-host", "authority_invalid"),
    ("unprotected", "authority_invalid"),
    ("symlink-pin", "authority_invalid"),
    ("writable-pin", "authority_invalid"),
    ("different-bytes", "subject_mismatch"),
    ("non-executable", "subject_mismatch"),
    ("unsafe-ancestor", "subject_mismatch"),
    ("symlink-image", "subject_mismatch"),
    ("symlink-release", "subject_mismatch"),
    ("wrong-image-path", "subject_mismatch"),
    ("direct-image", "subject_mismatch"),
    ("direct-managed-link", "subject_mismatch"),
])
def test_managed_grok_requires_pin_and_exact_trusted_native_path(
    managed_grok, monkeypatch, tmp_path, change, code,
):
    from phase_loop_runtime import seat_profile_grok

    env, native, digest, pin = managed_grok
    release = native.parents[1]
    original = pin.read_bytes()
    doc = json.loads(original)
    entry = doc["releases"][release.name]
    if change == "missing":
        pin.unlink()
    elif change == "other-release":
        doc["releases"] = {"other-release": entry}
    elif change == "noncanonical":
        pin.write_bytes(original + b"\n")
    elif change == "duplicate":
        pin.write_bytes(original.replace(b'"version":', b'"version":"1.0.92","version":'))
    elif change == "extra-field":
        entry["extra"] = True
    elif change == "unsafe-release":
        doc["releases"]["../other"] = entry
    elif change == "plus-release":
        doc["releases"]["other+1"] = entry
    elif change == "at-release":
        doc["releases"]["other@1"] = entry
    elif change == "dash-leading-release":
        doc["releases"]["-other"] = entry
    elif change == "dot-leading-release":
        doc["releases"][".other"] = entry
    elif change == "long-release":
        doc["releases"]["a" * 256] = entry
    elif change == "unselected-unapproved":
        doc["releases"]["other"] = {**entry, "binary_sha256": "f" * 64}
    elif change == "wrong-version":
        entry["version"] = "1.0.93"
    elif change == "wrong-platform":
        entry["platform"] = "linux-arm64"
    elif change == "wrong-host":
        monkeypatch.setattr(seat_subject, "platform", SimpleNamespace(machine=lambda: "aarch64"))
    elif change == "unprotected":
        monkeypatch.delitem(seat_profile_grok.JAIL_PROTECTION, digest)
    elif change == "symlink-pin":
        real = pin.rename(pin.with_suffix(".real"))
        pin.symlink_to(real)
    elif change == "writable-pin":
        pin.chmod(0o666)
    elif change == "different-bytes":
        native.write_bytes(b"\x7fELFchanged")
    elif change == "non-executable":
        native.chmod(0o644)
    elif change == "unsafe-ancestor":
        release.parent.parent.chmod(0o777)
    elif change == "symlink-image":
        archive = native.rename(release / "bin/grok-native")
        native.symlink_to(archive)
    elif change == "symlink-release":
        archive = tmp_path / "archive"
        release.rename(archive)
        release.symlink_to(archive, target_is_directory=True)
    elif change == "wrong-image-path":
        wrong = _exe(release / "other/grok", native.read_bytes())
        _frontdoor(release / "bin", release, wrong, leg="grok")
    elif change == "direct-image":
        env = {"PATH": str(native.parent)}
    elif change == "direct-managed-link":
        door = release / "bin/grok"
        door.unlink()
        door.symlink_to(_exe(tmp_path / "standalone/grok", native.read_bytes()))
    canonical = rfc8785.dumps(doc)
    if canonical != original:
        pin.write_bytes(canonical)

    with pytest.raises(ExecutableDependencyError) as refused:
        seat_subject.resolve_seat_subject("grok", env)
    assert refused.value.code == code


def test_grok_dependency_lease_refuses_before_path_lookup(monkeypatch):
    monkeypatch.setattr(seat_subject, "_current_dependency", lambda _leg: object())
    monkeypatch.setattr(seat_subject.shutil, "which", lambda *_a, **_k: pytest.fail("PATH lookup"))

    with pytest.raises(ExecutableDependencyError) as refused:
        seat_subject.resolve_seat_subject("grok", {"PATH": ""})
    assert refused.value.code == "authority_invalid"


@pytest.mark.parametrize("managed_grok", ["image-pin-only"], indirect=True)
@pytest.mark.parametrize("source", ["managed_image", "unexpected"])
def test_jailed_subject_refuses_unadmitted_source(managed_grok, monkeypatch, source):
    from phase_loop_runtime import seat_qualification_key

    env, _native, _sha256, pin = managed_grok
    resolved = seat_subject.resolve_seat_subject("grok", env)
    pin.unlink()
    stale = replace(resolved, source=source)
    monkeypatch.setattr(seat_subject, "resolve_seat_subject", lambda *_: stale)
    monkeypatch.setattr(seat_subject, "open_managed_authority",
                        lambda *_: pytest.fail("opened a dependency authority"))
    calls = []
    monkeypatch.setattr(seat_qualification_key, "admit_profile_projection",
                        lambda *args: calls.append(args))
    with pytest.raises(ExecutableDependencyError) as refused:
        panel_invoker._resolved_jail_subject("grok", env)
    assert refused.value.code == ("authority_missing" if source == "managed_image"
                                  else "subject_mismatch")
    assert calls == []


def test_managed_image_requires_grok_no_projection_profile(managed_grok):
    from phase_loop_runtime import seat_profiles

    env, _native, _sha256, _pin = managed_grok
    subject = seat_subject.resolve_seat_subject("grok", env)
    profile = seat_profiles.profile_for("grok")
    for invalid_subject, invalid_profile in (
        (subject, None),
        (subject, seat_profiles.profile_for("claude")),
        (subject, replace(profile, projection="optional")),
        (replace(subject, requirement=object()), profile),
        (replace(subject, leg="claude"), profile),
    ):
        with pytest.raises(ExecutableDependencyError) as refused:
            seat_subject.verify_managed_image(invalid_subject, invalid_profile)
        assert refused.value.code == "authority_invalid"
    with pytest.raises(ExecutableDependencyError) as refused:
        seat_subject.open_managed_authority(subject)
    assert refused.value.code == "authority_missing"


def test_managed_claude_subject_reads_package_json_version_without_executing(
    managed_fs, tmp_path, monkeypatch
):
    import subprocess

    _root, releases, pin = managed_fs
    release, native = _release(releases)
    pkg = native.parent / "package.json"
    pkg.write_text(
        json.dumps({
            "name": "@anthropic-ai/claude-code-linux-x64",
            "version": "2.1.331",
            "files": [native.name],
        }),
        encoding="utf-8",
    )
    pkg.chmod(0o644)
    door = _frontdoor(tmp_path / "bin", release, native)
    _pin(pin, release.name)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("must not execute claude binary")
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn claude binary")
    )

    subject = _resolve(door.parent)

    assert subject.source == "managed_release"
    assert subject.provider_version == "2.1.331"


@pytest.mark.parametrize("case", [
    "missing", "symlink", "malformed", "invalid_value", "prerelease", "empty_suffix",
    "oversized", "wrong_package", "unlisted_binary",
])
def test_claude_subject_version_falls_back_to_unknown_without_failing(
    managed_fs, tmp_path, case
):
    _root, releases, pin = managed_fs
    release, native = _release(releases, release_id=f"rel-{case}")
    pkg = native.parent / "package.json"
    if case == "symlink":
        target = tmp_path / "external-package.json"
        target.write_text(
            json.dumps({
                "name": "@anthropic-ai/claude-code-linux-x64",
                "version": "2.1.331",
                "files": [native.name],
            }),
            encoding="utf-8",
        )
        pkg.symlink_to(target)
    elif case == "malformed":
        pkg.write_text("{not-json", encoding="utf-8")
        pkg.chmod(0o644)
    elif case == "invalid_value":
        pkg.write_text(
            json.dumps({
                "name": "@anthropic-ai/claude-code-linux-x64",
                "version": "2.1.331 private-secret",
                "files": [native.name],
            }),
            encoding="utf-8",
        )
        pkg.chmod(0o644)
    elif case == "prerelease":
        pkg.write_text(
            json.dumps({
                "name": "@anthropic-ai/claude-code-linux-x64",
                "version": "2.1.331-rc.1",
                "files": [native.name],
            }),
            encoding="utf-8",
        )
        pkg.chmod(0o644)
    elif case == "empty_suffix":
        pkg.write_text(
            json.dumps({
                "name": "@anthropic-ai/claude-code-linux-x64",
                "version": "2.1.331-..",
                "files": [native.name],
            }),
            encoding="utf-8",
        )
        pkg.chmod(0o644)
    elif case == "oversized":
        pkg.write_text(
            '{"name": "@anthropic-ai/claude-code-linux-x64", "files": ["claude"], '
            '"version": "2.1.331", "pad": "' + ("x" * 70_000) + '"}',
            encoding="utf-8",
        )
        pkg.chmod(0o644)
    elif case == "wrong_package":
        pkg.write_text(
            json.dumps({"name": "unrelated-pkg", "version": "2.1.331", "files": [native.name]}),
            encoding="utf-8",
        )
        pkg.chmod(0o644)
    elif case == "unlisted_binary":
        pkg.write_text(
            json.dumps({
                "name": "@anthropic-ai/claude-code-linux-x64",
                "version": "2.1.331",
                "files": ["other-binary"],
            }),
            encoding="utf-8",
        )
        pkg.chmod(0o644)
    door = _frontdoor(tmp_path / f"bin-{case}", release, native)
    _pin(pin, release.name)

    subject = _resolve(door.parent)

    assert subject.source == "managed_release"
    assert subject.provider_version == "unknown"


def test_standalone_claude_subject_records_unknown_without_managed_provenance(
    managed_fs, tmp_path
):
    _root, _releases, _pin_path = managed_fs
    pkg_root = tmp_path / "claude-pkg"
    exe = _exe(pkg_root / "bin/claude", b"standalone")
    (pkg_root / "package.json").write_text(
        json.dumps({
            "name": "@anthropic-ai/claude-code",
            "version": "2.1.330",
            "bin": {"claude": "bin/claude"},
        }),
        encoding="utf-8",
    )

    subject = seat_subject.resolve_seat_subject("claude", {"PATH": str(exe.parent)})

    assert subject.source == "standalone"
    assert subject.provider_version == "unknown"
