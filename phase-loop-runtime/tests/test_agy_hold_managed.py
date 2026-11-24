"""AGYFRESH lane F0: can a managed-release Gemini seat run a held agy image?

AGYFRESH §2.9 (IF-0-HOLD-4) asks whether a managed-release seat may execute an image
whose digest is not the release's pinned ``native/agy`` -- the last-known-good image a
HOLD would admit -- through the REAL route projection acquisition
(``seat_route._projection_for_launch``) and the REAL jail admission
(``panel_invoker._prepare_jailed_gemini`` and ``seat_jail.build_seat_jail``), without
any change to the authority path.

The world here is a synthetic managed release with the shape of a deployed one: a
guarded ``agy`` frontdoor, ``native/agy``, a subject-only declaration projected at
``/seat/bin/gemini`` under adapter and policy ``phase-loop-seat``, the release's
``authority.json``, and a canonical ``seat_authority_pin.v2`` pin. Only the trust roots
and owner sets are substituted, as ``test_seats_teamhost_subject.py`` does. Nothing in
the authority or jail path is mocked: only the agy admission result is, or (in the seam
case) the real ``gemini_heartbeat.admit`` runs over a synthetic qualification store and
the existing agent-harness#1602 last-known-good seam.

Outcome recorded by these tests: **refused**. The jailed managed route admits only the
authority's pinned subject digest; a held image with a different digest is refused at
``panel_invoker._prepare_jailed_gemini`` with ``gemini_heartbeat_capability_unavailable``
before any jail is built, and the jail itself executes only the authority-bound
projection bytes.
"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import rfc8785

from executable_dependency_test_support import directory_identity, file_identity
from phase_loop_runtime import agy_provenance as prov
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import executable_dependency_startup
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_profiles
from phase_loop_runtime import seat_route
from phase_loop_runtime import seat_subject
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime.seat_qualification_key import key_for_launch


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed seat")

# Two synthetic agy images. The held one is genuinely different bytes, so its digest
# differs from the pinned subject's (asserted, not assumed).
PINNED = b"\x7fELF" + b"synthetic pinned native agy 1.5.11\n" * 64
HELD = b"\x7fELF" + b"synthetic held qualified agy 1.5.3\n" * 64
HELP = b"synthetic help\n"
MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
RELEASE_ID = "sync-0000000000000000-f0f0f0f0f0f0"
ADAPTER = {"id": "phase-loop-seat", "version": "1"}
BASE_PROFILE = "1" * 64
GEMINI_DESTINATION = f"{seat_jail.SEAT_BIN}/gemini"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def _fixed_umask():
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def _isolated_agy_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(gh, "_local_capabilities", lambda: None)
    monkeypatch.setattr(q, "_LAST_KNOWN_GOOD_PROVIDER", None)
    q._HELP_MEMO.clear()
    q._REQUALIFIED.clear()


def _write(path: Path, data: bytes, mode: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def _canonical(document: dict) -> bytes:
    return rfc8785.dumps(document)


def _with_derived_id(document: dict, field: str) -> dict:
    unsigned = {key: value for key, value in document.items() if key != field}
    return {**document, field: _sha(_canonical(unsigned))}


@pytest.fixture
def managed(tmp_path, monkeypatch):
    """A managed release whose pinned ``native/agy`` is PINNED, plus a HELD image."""
    root = tmp_path / "root"
    releases = root / "opt/consiliency/tooling/releases"
    pin = root / "etc/consiliency/tooling/seat-authority.json"
    release = releases / RELEASE_ID
    node_bin = release / "node-v24.22.3-linux-x64/bin"
    native = _write(release / "native/agy", PINNED, 0o755)
    _write(release / "source/lib/user_agent_tools.py", b"# launcher\n", 0o644)
    node_bin.mkdir(parents=True)
    dependencies = release / "share/phase-loop/seat-dependencies/gemini"
    dependencies.mkdir(parents=True)
    pin.parent.mkdir(parents=True)
    for path in (root, *root.rglob("*")):
        if path.is_dir():
            path.chmod(0o755)
    uid, gid = os.getuid(), os.getgid()
    exclusions: list = []
    exclusions_sha256 = _sha(_canonical(exclusions))
    native_identity = file_identity(native)

    declaration = _with_derived_id({
        "schema": "org.agent-harness.executable-dependency-declaration.v1",
        "declaration_id": "0" * 64,
        "adapter": ADAPTER,
        "provider": "gemini",
        "policy": {"id": "phase-loop-seat", "version": "1"},
        "subject": {
            "source": str(native),
            "destination": GEMINI_DESTINATION,
            "kind": "file",
            "uid": uid,
            "gid": gid,
            "mode": "0755",
            "nlink": 1,
            "size": len(PINNED),
            "sha256": _sha(PINNED),
            "forwarding": "original-argv",
        },
        "entries": [],
        "base_system": {
            "base_profile_sha256": BASE_PROFILE,
            "exclusions_sha256": exclusions_sha256,
            "exclusions": exclusions,
        },
    }, "declaration_id")
    declaration_path = _write(dependencies / "declaration.json", _canonical(declaration), 0o644)

    authority = _with_derived_id({
        "schema": "org.agent-harness.executable-dependency-authority.v1",
        "authority_id": "0" * 64,
        "authority_version": 1,
        "adapter": ADAPTER,
        "subject": {"provider": "gemini", "executable": native_identity},
        "declaration": file_identity(declaration_path),
        "source_roots": [directory_identity(release)],
        "destination_policy": {
            "provider_destination": GEMINI_DESTINATION,
            "allowed_roots": [seat_jail.SEAT_BIN],
        },
        "owner_mode_policy": {
            "allowed_uids": [uid],
            "allowed_gids": [gid],
            "file_modes": ["0644", "0755"],
            "directory_modes": ["0755"],
            "symlink_mode": "0777",
            "single_link_files": True,
        },
        "limits": {
            "authority_bytes": 131_072,
            "declaration_bytes": 16_777_216,
            "entry_count": 1_024,
            "file_bytes": 536_870_912,
            "aggregate_file_bytes": 2_147_483_648,
            "path_bytes": 4_096,
            "link_text_bytes": 4_096,
        },
        "base_profile": {
            "base_profile_sha256": BASE_PROFILE,
            "exclusions_sha256": exclusions_sha256,
        },
        "provenance": {
            "issuer": "synthetic",
            "upstream_receipt_sha256": "2" * 64,
            "upstream_manifest_sha256": "3" * 64,
            "adapter_evidence_sha256": "4" * 64,
        },
        "activation_nonce": "5" * 64,
    }, "authority_id")
    authority_bytes = _canonical(authority)
    _write(dependencies / "authority.json", authority_bytes, 0o644)
    _write(pin, _canonical({
        "schema": "seat_authority_pin.v2",
        "releases": {RELEASE_ID: {"gemini": {
            "authority_sha256": _sha(authority_bytes),
            "authority_id": authority["authority_id"],
            "base_profile_sha256": BASE_PROFILE,
        }}},
    }), 0o644)

    bin_dir = tmp_path / "bin"
    _write(bin_dir / "agy", (
        "#!/bin/sh\n"
        f'export PATH={node_bin}:"$PATH"\n'
        f"exec /usr/bin/python3 -I {release}/source/lib/user_agent_tools.py launch"
        f" --provider agy --shared {native} --node-bin {node_bin} -- \"$@\"\n"
    ).encode(), 0o755)
    held = _write(tmp_path / "held/agy", HELD, 0o755)

    # Trust roots and owner sets only (production: root-owned /opt and /etc).
    owners = frozenset({0, os.geteuid()})
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", releases)
    monkeypatch.setattr(seat_subject, "MANAGED_AUTHORITY_PIN", pin)
    monkeypatch.setattr(seat_subject, "_PIN_WALK_ROOT", root)
    monkeypatch.setattr(seat_subject, "_PIN_OWNERS", owners)
    monkeypatch.setattr(seat_subject, "_MANAGED_OWNERS", owners)
    monkeypatch.setattr(panel, "_FRONTDOOR_RELEASES", releases)
    monkeypatch.setattr(panel, "_FRONTDOOR_OWNERS", owners)
    # No bound session lease: the managed release is the subject source.
    monkeypatch.setattr(
        executable_dependency_startup, "current_dependency_for_provider",
        lambda *_args, **_kwargs: None,
    )

    review = tmp_path / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True, mode=0o700)
    tree_fd = seat_jail.open_dir_nofollow(tree)
    try:
        staged = seat_jail.tree_manifest_sha256_at(tree_fd)
    finally:
        os.close(tree_fd)
    cert = _write(tmp_path / "egress/ca.crt", b"synthetic certificate\n", 0o644)
    assert _sha(HELD) != _sha(PINNED)
    return SimpleNamespace(
        native=native, held=held, env={"HOME": str(tmp_path), "PATH": str(bin_dir)},
        review=review, seat=tmp_path / "seat",
        authorization=SimpleNamespace(staged_tree_sha256=staged),
        egress=SimpleNamespace(ca_cert=cert, proxy_url="http://127.0.0.1:3128",
                               private_proxy_token=b"fixture"),
    )


def _prepare(world):
    return panel._prepare_jailed_gemini(
        world.review, world.seat, world.authorization, 1, os.getpid(),
        ("artifact", "instructions"), world.egress, env=world.env, credential="none",
    )


def _projected_bytes(jail) -> dict[str, bytes]:
    args = jail.dependency_mount_args
    files = {}
    for index, item in enumerate(args):
        if item == "--ro-bind-data":
            fd = int(args[index + 1])
            files[args[index + 2]] = os.pread(fd, os.fstat(fd).st_size, 0)
    return files


def _spy_jail_builds(monkeypatch):
    built = []
    real = seat_jail.build_seat_jail

    def spy(*args, **kwargs):
        built.append(args[2])
        return real(*args, **kwargs)

    monkeypatch.setattr(seat_jail, "build_seat_jail", spy)
    return built


def _admission_result(monkeypatch, data, path, admission_class, source):
    """Mock only the agy admission result; record what it returned and closed."""
    issued = []

    def admit(_env, *, subject_path=None, **_kwargs):
        image = gh.VerifiedImage.from_bytes(data, path)
        issued.append(SimpleNamespace(subject_path=subject_path, image=image))
        return gh.Admission(image, _sha(HELP), admission_class, path, source=source)

    monkeypatch.setattr(panel.gemini_heartbeat, "admit", admit)
    return issued


def _closed(image) -> bool:
    return image.fd is None  # VerifiedImage.close() closes the memfd and clears it


# --- the real authority and projection path ---------------------------------------


def test_fixture_resolves_through_the_real_managed_release_path(managed):
    subject = seat_subject.resolve_seat_subject("gemini", managed.env)
    assert subject.source == "managed_release"
    assert subject.release_id == RELEASE_ID
    assert subject.subject_path == managed.native
    assert subject.requirement.selected_executable.sha256 == _sha(PINNED)


def test_route_projection_acquisition_binds_the_pinned_subject(managed):
    profile = seat_profiles.profile_for("gemini")
    assert profile is not None and profile.projection == "optional"
    projection = seat_route._projection_for_launch(profile, managed.env)
    assert projection is not None and projection.projection_digest
    # The launch key is bound to that projection: a different projection is a different key.
    assert key_for_launch(profile, variant=None, allowlist_digest=None, projection=projection) != (
        key_for_launch(profile, variant=None, allowlist_digest=None, projection=None))
    subject, dependency = panel._resolved_jail_subject("gemini", managed.env)
    try:
        assert subject.source == "managed_release"
        assert dependency.subject_sha256 == _sha(PINNED)
        assert dependency.subject_destination == GEMINI_DESTINATION
        assert dependency.projection_digest == projection.projection_digest
    finally:
        dependency.close()


# --- control: the pinned subject passes the real jail admission ---------------------


def test_control_the_pinned_subject_passes_real_jail_admission(managed, monkeypatch):
    from test_gemini_seat_egress_1170 import _assert_credential_free_gemini_jail

    built = _spy_jail_builds(monkeypatch)
    issued = _admission_result(monkeypatch, PINNED, managed.native, "release_qualified", "subject")
    seat = _prepare(managed)
    try:
        assert [item.subject_path for item in issued] == [managed.native]
        assert seat.image_sha256 == _sha(PINNED)
        assert built == [managed.native, managed.native]
        for jail in (seat.jail, seat.probe_jail):
            assert jail.provider_argv0 == GEMINI_DESTINATION
            assert jail.dependency_projection_digest
            assert seat_jail.actual_profile_digest(jail) == seat_jail.jail_profile_digest("gemini")
            _assert_credential_free_gemini_jail(jail, seat.private_proxy_token)
            assert _projected_bytes(jail) == {GEMINI_DESTINATION: PINNED}
    finally:
        seat_jail.close_jail_fds(seat.jail)
        seat_jail.close_jail_fds(seat.probe_jail)
        seat.jail.dependency.close()


# --- the probe: a held image with a different digest -------------------------------


@pytest.mark.parametrize("admission_class", ["release_qualified", "locally_qualified"])
def test_managed_seat_refuses_a_held_image_with_a_different_digest(
    managed, monkeypatch, admission_class,
):
    built = _spy_jail_builds(monkeypatch)
    issued = _admission_result(monkeypatch, HELD, managed.held, admission_class, "lkg")
    with pytest.raises(ValueError, match="^gemini_heartbeat_capability_unavailable$"):
        _prepare(managed)
    # The admission DID return the held image (this is not a lookup miss) ...
    assert [item.subject_path for item in issued] == [managed.native]
    assert issued[0].image.sha256 == _sha(HELD) != _sha(PINNED)
    # ... and the managed digest gate refused it: closed, no jail built, nothing staged.
    assert _closed(issued[0].image)
    assert built == []
    assert not managed.seat.exists()


def test_real_admission_through_the_1602_seam_is_refused_on_the_managed_route(
    managed, monkeypatch,
):
    """No admission mock: the real ``gh.admit`` misses the unqualified pinned subject and
    the existing last-known-good seam supplies HELD, locally qualified in a synthetic
    store. The managed route still refuses it."""
    digest = _sha(HELD)
    store = q.Store()
    store.create()
    key = q.agy_profile_digest()
    asset = SimpleNamespace(name=HOST.asset, version="1.5.3", digest="sha256:" + "0" * 64)
    store.put_provenance(SimpleNamespace(image_sha256=digest, platform=HOST.name, asset=asset), key)
    store.put_qualified(digest, _sha(HELP), HOST, key, "1.5.3")
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: True)
    monkeypatch.setattr(q, "_run_help", lambda *_: HELP)
    q.register_last_known_good(lambda: gh.VerifiedImage.from_bytes(HELD, managed.held))

    returned = []
    real_admit = gh.admit

    def record(*args, **kwargs):
        admission = real_admit(*args, **kwargs)
        returned.append(admission)
        return admission

    monkeypatch.setattr(panel.gemini_heartbeat, "admit", record)
    built = _spy_jail_builds(monkeypatch)
    with pytest.raises(ValueError, match="^gemini_heartbeat_capability_unavailable$"):
        _prepare(managed)
    assert [(item.source, item.admission_class, item.image.sha256) for item in returned] == [
        ("lkg", "locally_qualified", digest)]
    assert _closed(returned[0].image)
    assert built == []


# --- why no route around the gate exists without touching authority or jail ---------


def test_jail_admission_executes_only_the_authority_bound_subject(managed):
    subject, dependency = panel._resolved_jail_subject("gemini", managed.env)
    review = managed.review
    config = review / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
    panel._write_gemini_config(config, b"")
    common = dict(
        tree=review / seat_jail.HOST_TREE_DIRNAME, seat_ids=(3, 3),
        gemini_config=config, egress_ca=managed.egress.ca_cert,
        egress_proxy=managed.egress.proxy_url, dependency=dependency,
    )
    try:
        # Handing the jail the held image's path is an identity refusal ...
        (review / "held").mkdir()
        bundle = seat_jail.memfd_with("b", b"B")
        brief = seat_jail.memfd_with("i", b"I")
        try:
            with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
                seat_jail.build_seat_jail(
                    "gemini", review / "held", managed.held,
                    bundle_memfd=bundle, instructions_memfd=brief, **common)
            assert refused.value.code == seat_jail.refused("identity")
        finally:
            os.close(bundle)
            os.close(brief)
        # ... and the subject's jail binds the authority's bytes, whatever was admitted.
        (review / "pinned").mkdir()
        jail = seat_jail.build_seat_jail(
            "gemini", review / "pinned", managed.native,
            bundle_memfd=seat_jail.memfd_with("b", b"B"),
            instructions_memfd=seat_jail.memfd_with("i", b"I"), **common)
        try:
            # No path bind of a provider: only the projection's sealed bytes are mounted.
            assert GEMINI_DESTINATION not in [
                jail.process_owner[i + 2] for i, item in enumerate(jail.process_owner)
                if item == "--ro-bind"]
            assert _projected_bytes(jail) == {GEMINI_DESTINATION: PINNED}
        finally:
            seat_jail.close_jail_fds(jail)
    finally:
        dependency.close()


def test_putting_the_held_bytes_at_the_subject_path_is_an_authority_refusal(managed):
    _write(managed.native, HELD, 0o755)
    profile = seat_profiles.profile_for("gemini")
    with pytest.raises(ExecutableDependencyError) as caught:
        seat_route._projection_for_launch(profile, managed.env)
    assert caught.value.code == "subject_mismatch"
    with pytest.raises(ExecutableDependencyError) as jailed:
        panel._resolved_jail_subject("gemini", managed.env)
    assert jailed.value.code == "subject_mismatch"


# --- AGYFRESH HOLD, lane SL-2: the managed skip (AGYFRESH §2.9 outcome; R-F0-1, R-F0-2) ----
# Appended after the eight F0 tests above, which are unmodified. F0 failed, so the hold skips
# every managed-release subject, by its resolved path, at the one admission boundary: on
# every route nothing is searched or opened and today's refusal stands (EC-HOLD-6, second
# branch). The jailed standalone case is the STOP branches' control (lanes artifact §K2):
# before SL-3 a held admission carries no path and that route refuses it.

from phase_loop_runtime import agy_hold  # noqa: E402
from phase_loop_runtime import agy_integrity  # noqa: E402

MEMBER = b"\x7fELF" + b"synthetic held release member 1.5.3\n" * 64
STANDALONE = b"\x7fELF" + b"synthetic standalone unqualified agy 9.9.9\n" * 64


def _no_network(*_args, **_kwargs):
    raise prov.ProvenanceError(prov.UNVERIFIED)


@pytest.fixture
def hold_world(managed, tmp_path, monkeypatch):
    """The F0 managed release, plus a held release member in a vendor store and in ``held/``."""
    monkeypatch.setattr(agy_hold, "_WALK_ROOT", tmp_path)
    vendor = tmp_path / "vendor"
    _write(vendor / f"1.5.3-{_sha(MEMBER)[:16]}" / "agy", MEMBER, 0o755)
    for path in (vendor, *vendor.iterdir()):
        path.chmod(0o755)
    monkeypatch.setattr(agy_hold, "VENDOR_STORES", (vendor,))
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {_sha(MEMBER): _sha(HELP)})
    monkeypatch.setattr(gh, "catalog_members", lambda path=None: [
        {"release_version": "1.5.3", "image_sha256": _sha(MEMBER), "help_sha256": _sha(HELP)}])
    store = q.Store()
    store.create()
    held = store.host_dir / agy_hold.HELD_DIRNAME
    held.mkdir(mode=0o700)
    _write(held / _sha(MEMBER), MEMBER, 0o600)
    monkeypatch.setattr(prov, "find_provenance", _no_network)
    monkeypatch.setattr(q, "_run_help", lambda *_: HELP)
    standalone = _write(tmp_path / "standalone-bin" / "agy", STANDALONE, 0o755)
    return SimpleNamespace(managed=managed, vendor=vendor, held=held, standalone=standalone,
                           standalone_env={"HOME": str(tmp_path), "PATH": str(standalone.parent)})


def _hold_openers(monkeypatch):
    """Every anchor, directory and candidate the hold opens."""
    calls = []
    for name in ("open_anchor", "_open_dir_at", "_open_candidate"):
        real = getattr(agy_hold, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(agy_hold, name, spy)
    return calls


def _both_paths_refuse(env, subject, preflight_code):
    with pytest.raises(ValueError, match=f"^{preflight_code}$"):
        q.admit_seat(env, subject, first_use=True)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="^agy_image_unqualified$"):
        agy_integrity.admit_for_seat(subject, env)


def test_ec_hold_6_an_unqualified_managed_subject_is_never_held(hold_world, monkeypatch):
    world = hold_world.managed
    calls = _hold_openers(monkeypatch)
    _both_paths_refuse(world.env, world.native, prov.UNVERIFIED)
    assert calls == []
    # Control: the same images with a standalone subject are held.
    admission = q.admit_seat(hold_world.standalone_env, hold_world.standalone)
    try:
        assert (admission.source, admission.image.sha256) == ("lkg", _sha(MEMBER))
    finally:
        admission.close()
    assert calls


@pytest.mark.parametrize("alias", ["managed_root", "subject"])
def test_ec_hold_6_the_managed_skip_holds_through_a_symlink_alias(hold_world, tmp_path, monkeypatch, alias):
    world = hold_world.managed
    subject = world.native
    if alias == "managed_root":
        aliased = tmp_path / "releases-alias"
        aliased.symlink_to(seat_subject.MANAGED_RELEASES_ROOT, target_is_directory=True)
        monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", aliased)
    else:
        subject = tmp_path / "agy-alias"
        subject.symlink_to(world.native)
    calls = _hold_openers(monkeypatch)
    _both_paths_refuse(world.env, subject, prov.UNVERIFIED)
    assert calls == []


def test_ec_hold_6_a_managed_subject_removed_after_resolution_is_still_managed(hold_world, monkeypatch):
    world = hold_world.managed
    subject = seat_subject.resolve_seat_subject("gemini", world.env).subject_path
    assert subject == world.native
    subject.unlink()
    calls = _hold_openers(monkeypatch)
    _both_paths_refuse(world.env, subject, "gemini_heartbeat_capability_unavailable")
    assert calls == []


def test_ec_hold_6_route_2_skips_a_path_agy_that_is_the_guarded_frontdoor(hold_world, tmp_path, monkeypatch):
    """The deployed layout: PATH names ``current/bin/agy``, a link to the release's own
    guarded frontdoor below the managed root."""
    world = hold_world.managed
    release = world.native.parents[1]
    _write(release / "bin" / "agy", (tmp_path / "bin" / "agy").read_bytes(), 0o755)
    current = tmp_path / "current"
    current.symlink_to(release, target_is_directory=True)
    env = {**world.env, "PATH": str(current / "bin")}
    calls = _hold_openers(monkeypatch)
    with pytest.raises(ValueError, match="^gemini_heartbeat_capability_unavailable$"):
        gh.admit(env)
    with pytest.raises(ValueError, match="^gemini_heartbeat_capability_unavailable$"):
        gh.require_capability(env)
    assert calls == []


def test_ec_hold_6_a_path_agy_outside_the_managed_root_is_standalone(hold_world, monkeypatch):
    calls = _hold_openers(monkeypatch)
    admission = gh.admit(hold_world.standalone_env)
    try:
        assert (admission.source, admission.hold_reason, admission.image.sha256) == (
            "lkg", "subject_unqualified", _sha(MEMBER))
    finally:
        admission.close()
    assert "_open_candidate" in calls


def test_jailed_standalone_route_refuses_a_held_admission_before_any_jail(hold_world, monkeypatch):
    """Before SL-3 (and for good on a STOP branch): a held admission has no path, and the
    jailed standalone route refuses it with today's code without building a jail."""
    world = hold_world.managed
    standalone = SimpleNamespace(**{**vars(world), "env": hold_world.standalone_env})
    subject = seat_subject.resolve_seat_subject("gemini", standalone.env)
    assert (subject.source, subject.subject_path) == ("standalone", hold_world.standalone)
    held = q.admit_seat(standalone.env, subject.subject_path)
    try:
        assert (held.source, held.path) == ("lkg", None)
    finally:
        held.close()
    issued = []
    real_admit = gh.admit

    def record(*args, **kwargs):
        admission = real_admit(*args, **kwargs)
        issued.append(admission)
        return admission

    monkeypatch.setattr(panel.gemini_heartbeat, "admit", record)
    built = _spy_jail_builds(monkeypatch)
    with pytest.raises(ValueError, match="^gemini_heartbeat_capability_unavailable$"):
        _prepare(standalone)
    assert [(item.source, item.path, item.image.sha256) for item in issued] == [("lkg", None, _sha(MEMBER))]
    assert _closed(issued[0].image)
    assert built == []
