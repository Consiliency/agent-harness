"""Seat-only agy admission: ``agy_integrity.admit_for_seat`` (agent-harness#1333 PR1).

The two owned review-seat sites in ``seat_profile`` (the credential refresh and the owned
non-heartbeat seat) admit a release member offline first, then a ``locally_qualified``
image through ``agy_qualification.lookup``. A miss, the opt-out, a failed or tampered record,
an unsafe store, an unreadable image or a seal failure is the typed ``agy_image_unqualified``
refusal; a refusal that already carries its own typed code passes through. ``agy_integrity.check`` stays
release-only for its executor and canary callers; one cell per caller pins that.

Nothing here reaches the network or a model: help measurement is a counting fake (except
in the re-entrancy cells, which run the real measurement down to the launch), the store is
seeded directly, and machine-id and platform are injected.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

q = pytest.importorskip("phase_loop_runtime.agy_qualification")

from phase_loop_runtime import agy_integrity  # noqa: E402
from phase_loop_runtime import agy_provenance as prov  # noqa: E402
from phase_loop_runtime import gemini_heartbeat as gh  # noqa: E402
from phase_loop_runtime import panel_invoker as pi  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "memfd_create"),
    reason="Linux sealed-memfd image-admission contract",
)

MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
HELP = b"synthetic help\n"
_REAL_HELP = q._run_help


def _token(home, expiry):
    path = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"auth_method": "oauth", "token": {
        "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
        "token_type": "Bearer", "expiry": expiry.isoformat()}}))
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A synthetic, non-member agy and an empty per-user store; help is a counting fake."""
    q._HELP_MEMO.clear()
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {"f" * 64: "e" * 64})
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "ran"
    image = f"#!/bin/sh\ntouch '{marker}'\necho synthetic agy 9.9.9\n".encode()
    agy = bindir / "agy"
    agy.write_bytes(image)
    agy.chmod(0o755)
    home = tmp_path / "home"
    _token(home, datetime.now(timezone.utc) + timedelta(hours=1))
    helps = []

    def fake_help(verified, env):
        helps.append(verified.sha256)
        return HELP

    monkeypatch.setattr(q, "_run_help", fake_help)
    return SimpleNamespace(tmp=tmp_path, agy=agy, image=image, digest=sha256(image).hexdigest(),
                           marker=marker, home=home, helps=helps,
                           env={"PATH": str(bindir), "HOME": str(home)})


def _seed(world):
    """A real ``locally_qualified`` record for the world's image (provenance + qualified)."""
    store = q.Store()
    store.create()
    runtime = q.runtime_identity()
    asset = SimpleNamespace(name=HOST.asset, version="9.9.9", digest="sha256:" + "0" * 64)
    store.put_provenance(SimpleNamespace(image_sha256=world.digest, platform=HOST.name, asset=asset), runtime)
    store.put_qualified(world.digest, sha256(HELP).hexdigest(), HOST, runtime, "9.9.9")
    return store


def _admits(world):
    image = agy_integrity.admit_for_seat(str(world.agy), world.env)
    try:
        assert image.sha256 == world.digest
        assert os.pread(image.fd, 1 << 20, 0) == world.image
    finally:
        image.close()


def _open_fds():
    return sorted(os.listdir("/proc/self/fd"))


# ------------------------------------------------------------------ admit_for_seat

def test_a_release_member_admits_offline_with_self_qualification_disabled(world, monkeypatch):
    """Release members are admitted before any config or store read."""
    monkeypatch.setitem(gh.QUALIFIED_IMAGES, world.digest, "e" * 64)
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: False)
    monkeypatch.setattr(q, "lookup", lambda *a, **k: pytest.fail("a release member reached lookup"))
    monkeypatch.setattr(q, "Store", lambda *a, **k: pytest.fail("a release member read the store"))
    _admits(world)
    assert world.helps == []


def test_a_locally_qualified_image_admits_and_carries_the_admitted_bytes(world):
    _seed(world)
    image = agy_integrity.admit_for_seat(str(world.agy), world.env)
    try:
        world.agy.write_bytes(b"#!/bin/sh\necho swapped after admission\n")
        assert image.sha256 == world.digest
        assert os.pread(image.fd, 1 << 20, 0) == world.image
        descriptor = image.reopen()
        try:
            assert os.pread(descriptor, 1 << 20, 0) == world.image
        finally:
            os.close(descriptor)
    finally:
        image.close()
    assert world.helps == [world.digest]


def _flip(store):
    for path in store.host_dir.iterdir():
        if path.name.startswith(("qualified-", "provenance-")):
            raw = bytearray(path.read_bytes())
            raw[-5] ^= 1
            path.write_bytes(bytes(raw))


@pytest.mark.parametrize("state", ["absent", "failed", "tampered", "loose", "opted_out"])
def test_every_non_admission_is_the_typed_refusal(world, monkeypatch, state):
    """claude N3: lookup's untyped refusals (opt-out, a failed record) map to the typed one."""
    if state != "absent":
        store = _seed(world)
        if state == "failed":
            store.put_failed(world.digest, sha256(HELP).hexdigest(), HOST, q.runtime_identity(),
                             "completion", "synthetic")
        elif state == "tampered":
            _flip(store)
        elif state == "loose":
            store.host_dir.chmod(0o755)
        elif state == "opted_out":
            monkeypatch.setattr(q, "self_qualification_enabled", lambda: False)
    before = _open_fds()
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="^agy_image_unqualified$"):
        agy_integrity.admit_for_seat(str(world.agy), world.env)
    assert _open_fds() == before
    if state in {"failed", "opted_out"}:
        assert world.helps == []


def test_an_admission_miss_closes_the_carried_image(world, monkeypatch):
    real_lookup = q.lookup
    misses = []

    def spy(env, data, path, **kwargs):
        try:
            return real_lookup(env, data, path, **kwargs)
        except gh.AdmissionMiss as miss:
            misses.append(miss.image)
            raise

    monkeypatch.setattr(q, "lookup", spy)
    before = _open_fds()
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        agy_integrity.admit_for_seat(str(world.agy), world.env)
    assert len(misses) == 1 and misses[0].fd is None
    assert _open_fds() == before


def test_a_memfd_seal_failure_in_lookup_is_the_typed_refusal(world, monkeypatch):
    """Fault injection: lookup's ``VerifiedImage.from_bytes`` raises the seal error.

    Mutation: dropping ``AgyCanaryEvidenceError`` from the mapped exceptions lets it escape.
    """
    from phase_loop_runtime.agy_canary_evidence import AgyCanaryEvidenceError

    _seed(world)

    def unsealable(**_kwargs):
        raise AgyCanaryEvidenceError("synthetic memfd seal failure")

    monkeypatch.setattr(gh, "_sealed_tree_fd", unsealable)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="^agy_image_unqualified$") as caught:
        agy_integrity.admit_for_seat(str(world.agy), world.env)
    assert isinstance(caught.value.__cause__, AgyCanaryEvidenceError)


@pytest.mark.parametrize("code", ["seat_filtered_egress_unavailable", "seat_profile_unavailable"])
def test_a_refusal_with_its_own_typed_code_passes_through(world, monkeypatch, code):
    """A typed seat refusal raised inside lookup (e.g. by the help measurement) keeps its code."""
    from phase_loop_runtime import sandbox_egress

    exc_type = (sandbox_egress.EgressUnavailable if code == "seat_filtered_egress_unavailable"
                else sandbox_egress.SeatIdentityUnverified)

    def refuse(*_args, **_kwargs):
        raise exc_type(code)

    monkeypatch.setattr(q, "lookup", refuse)
    with pytest.raises(exc_type, match=code) as caught:
        agy_integrity.admit_for_seat(str(world.agy), world.env)
    assert pi._exception_failure(caught.value) == code


def _quiescence_or_sandbox_refusal(kind):
    from phase_loop_runtime import seat_jail

    if kind == "gemini_quiescence":
        return gh.GeminiQuiescenceError("synthetic: agy process tree still alive")
    if kind == "provider_group_quiescence":
        return pi.ProviderProcessGroupQuiescenceError("synthetic: provider group not proven absent")
    return seat_jail.SeatSandboxRefused(seat_jail.refused("namespace"), "synthetic jail refusal")


@pytest.mark.parametrize("kind", ["gemini_quiescence", "provider_group_quiescence", "seat_sandbox_refused"])
def test_a_quiescence_or_sandbox_refusal_in_lookup_keeps_its_type(world, monkeypatch, kind):
    """agent-harness#1350 president follow-up. The help measurement can end in a quiescence
    failure or a jail refusal; each must reach its own handler (the leg's quiescence path,
    the sandbox notice), never be relabelled ``agy_image_unqualified``. Nothing is admitted
    and no descriptor leaks.

    Mutation: dropping the class from the re-raise in ``_locally_qualified``.
    """
    _seed(world)
    raised = _quiescence_or_sandbox_refusal(kind)
    real_lookup = q.lookup

    def refuse(env, data, path, **kwargs):
        image = gh.VerifiedImage.from_bytes(data, path)
        image.close()  # lookup's own cleanup before it propagates
        raise raised

    monkeypatch.setattr(q, "lookup", refuse)
    before = _open_fds()
    with pytest.raises(type(raised)) as caught:
        agy_integrity.admit_for_seat(str(world.agy), world.env)
    assert caught.value is raised and type(caught.value) is type(raised)
    assert not isinstance(caught.value, agy_integrity.AgyImageUnqualified)
    assert _open_fds() == before
    monkeypatch.setattr(q, "lookup", real_lookup)
    _admits(world)  # the seeded record still admits once the fault is gone


def test_the_quiescence_subclass_does_not_shield_a_seal_failure(world, monkeypatch):
    """``ProviderProcessGroupQuiescenceError`` subclasses ``AgyCanaryEvidenceError``; the base
    class (a real memfd seal failure) is still the typed refusal.

    Mutation: re-raising ``AgyCanaryEvidenceError`` instead of only the subclass.
    """
    from phase_loop_runtime.agy_canary_evidence import AgyCanaryEvidenceError

    assert issubclass(pi.ProviderProcessGroupQuiescenceError, AgyCanaryEvidenceError)

    def refuse(*_args, **_kwargs):
        raise AgyCanaryEvidenceError("synthetic memfd seal failure")

    monkeypatch.setattr(q, "lookup", refuse)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="^agy_image_unqualified$") as caught:
        agy_integrity.admit_for_seat(str(world.agy), world.env)
    assert type(caught.value.__cause__) is AgyCanaryEvidenceError


def test_the_refusal_notice_names_the_real_remedies():
    """agent-harness#1350 board: the fix is first use or the opt-out, never a downgrade."""
    from phase_loop_runtime import seat_jail

    notice = seat_jail.render_notice("agy_image_unqualified", "gemini:a")
    assert "phase-loop agy-qualification run" in notice.fix
    assert "[agy] self_qualification" in notice.fix
    assert "install" not in notice.fix


def test_a_missing_executable_is_the_typed_refusal(world):
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        agy_integrity.admit_for_seat(str(world.tmp / "absent" / "agy"), world.env)


# ----------------------------------------------------------- the two seat call sites

def _spy_admit(monkeypatch):
    calls = []
    real = agy_integrity.admit_for_seat

    def spy(path, env):
        calls.append((str(path), dict(env)))
        return real(path, env)

    monkeypatch.setattr(agy_integrity, "admit_for_seat", spy)
    return calls


def _bound_provider(profile):
    args = profile.mount_args
    index = next(i for i, arg in enumerate(args)
                 if arg == "--ro-bind-data" and args[i + 2] == "/run/phase-loop-seat/provider")
    return int(args[index + 1])


def test_the_owned_non_heartbeat_seat_admits_a_locally_qualified_image(world, monkeypatch):
    """PI:4774. Mutation: leaving the site on ``check`` refuses the local image."""
    _seed(world)
    calls = _spy_admit(monkeypatch)
    cwd = world.tmp / "out"
    cwd.mkdir()
    with pi.seat_profile(harness="gemini", executable=str(world.agy), env=world.env, cwd=cwd) as (
            destination, profile):
        assert destination == "/run/phase-loop-seat/provider"
        assert os.pread(_bound_provider(profile), 1 << 20, 0) == world.image
    assert [path for path, _env in calls] == [str(world.agy)]
    assert calls[0][1]["HOME"] == str(world.home)


def test_the_credential_refresh_admits_a_locally_qualified_image(world, monkeypatch):
    """PI:4679 (``gemini_profile is None``). Mutation: leaving the site on ``check``."""
    _seed(world)
    _token(world.home, datetime.now(timezone.utc) - timedelta(minutes=1))
    calls = _spy_admit(monkeypatch)
    refreshed = []

    def refresh(home, image):
        refreshed.append((home, image.sha256, os.pread(image.fd, 1 << 20, 0)))

    monkeypatch.setattr(pi, "_refresh_gemini_credential", refresh)
    cwd = world.tmp / "out"
    cwd.mkdir()
    with pi.seat_profile(harness="gemini", executable=str(world.agy), env=world.env, cwd=cwd):
        pass
    assert refreshed == [(world.home, world.digest, world.image)]
    assert [path for path, _env in calls] == [str(world.agy), str(world.agy)]


def test_an_unqualified_image_refuses_the_seat_with_its_typed_code(world, monkeypatch):
    calls = _spy_admit(monkeypatch)
    cwd = world.tmp / "out"
    cwd.mkdir()
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified") as caught:
        with pi.seat_profile(harness="gemini", executable=str(world.agy), env=world.env, cwd=cwd):
            pytest.fail("an unqualified image was admitted")
    assert len(calls) == 1
    assert pi._exception_failure(caught.value) == "agy_image_unqualified"


# ----------------------------------------------------------- re-entrancy (no recursion)

class _LaunchReached(Exception):
    pass


@pytest.mark.parametrize("credential", ["fresh", "near_expiry"])
def test_lookup_help_measurement_never_reenters_seat_admission(world, monkeypatch, credential):
    """The real help measurement runs down to the launch with its own profile, so it takes
    the profile branches of ``seat_profile`` and never reaches either admission site.

    Mutation: building the help launch without ``gemini_profile`` calls ``admit_for_seat``
    (recursing into lookup).
    """
    monkeypatch.setattr(q, "_run_help", _REAL_HELP)
    expiry = timedelta(hours=1) if credential == "fresh" else -timedelta(minutes=1)
    token = _token(world.home, datetime.now(timezone.utc) + expiry)
    admitted, checked, refreshed, launched = [], [], [], []
    monkeypatch.setattr(agy_integrity, "admit_for_seat", lambda *a, **k: admitted.append(a))
    monkeypatch.setattr(agy_integrity, "check", lambda *a, **k: checked.append(a))
    monkeypatch.setattr(pi, "_refresh_gemini_credential",
                        lambda home, image: refreshed.append(image.sha256))

    @contextmanager
    def owned_profile(env, *, settings_bytes, credential_path, admission):
        assert admission.admission_class == "qualification_candidate"
        settings = os.memfd_create("synthetic-settings", os.MFD_CLOEXEC)
        try:
            config = gh.PRIVATE_HOME + "/.gemini/antigravity-cli"
            mounts = []
            for directory in (gh.PRIVATE_HOME, gh.PRIVATE_HOME + "/.gemini", config):
                mounts += ["--perms", "0700", "--dir", directory]
            mounts += ["--symlink", str(Path(credential_path).absolute()), config + "/antigravity-oauth-token"]
            yield SimpleNamespace(
                executable=gh.PRIVATE_HOME + "/agy", env={"PATH": "/usr/bin:/bin", "HOME": gh.PRIVATE_HOME},
                mount_args=mounts, image_fd=admission.image.fd, settings_fd=settings,
                pass_fds=(admission.image.fd, settings),
                evidence={"provider_image_sha256": admission.image.sha256})
        finally:
            os.close(settings)

    def launch_owned(command, **kwargs):
        launched.append((command, kwargs["profile"].mount_args))
        raise _LaunchReached

    monkeypatch.setattr(gh, "owned_profile", owned_profile)
    monkeypatch.setattr(pi, "launch_owned", launch_owned)
    egress = pi._EGRESS_LAUNCH_PREFIX.set(("synthetic-filtered-namespace",))
    image = gh.VerifiedImage.from_bytes(world.image, str(world.agy))
    try:
        with pytest.raises(_LaunchReached):
            q._run_help(image, {"PATH": "/usr/bin:/bin", "HOME": str(world.home)})
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(egress)
        image.close()
    assert admitted == [] and checked == []
    assert len(launched) == 1 and launched[0][0][1:] == ["--help"]
    assert "--ro-bind-data" in launched[0][1]
    assert refreshed == ([] if credential == "fresh" else [world.digest])
    assert token.exists()


# ------------------------------------------- check stays release-only, per caller

@pytest.fixture
def locally_qualified(world, monkeypatch):
    """The world's image is locally qualified (``admit_for_seat`` admits it); every
    executor/canary caller must still refuse it, without consulting lookup."""
    _seed(world)
    _admits(world)
    real_lookup = q.lookup
    lookups = []

    def spy(*args, **kwargs):
        lookups.append(args)
        return real_lookup(*args, **kwargs)

    monkeypatch.setattr(q, "lookup", spy)
    world.lookups = lookups
    return world


def test_check_refuses_a_locally_qualified_image(locally_qualified):
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        agy_integrity.check(locally_qualified.agy)
    assert locally_qualified.lookups == []


@pytest.mark.parametrize("supervised", [False, True])
def test_the_trusted_executor_refuses_a_locally_qualified_image(locally_qualified, supervised):
    """launcher.py:2696 (``trusted_command``). Mutation: routing ``check`` through lookup."""
    from phase_loop_runtime import launcher

    world = locally_qualified
    descriptor = os.open(world.tmp / "lease", os.O_CREAT | os.O_RDWR, 0o600)

    class Lease:
        generation = "seat-admission-test"

        def fileno(self):
            return descriptor

    try:
        with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
            launcher.launch([str(world.agy)], cwd=world.tmp,
                            lease_authority=Lease() if supervised else None)
    finally:
        os.close(descriptor)
    assert not world.marker.exists()
    assert world.lookups == []


def test_the_executor_owned_launch_refuses_a_locally_qualified_image(locally_qualified):
    """PI ``launch_owned`` with ``EXECUTOR_TRUSTED`` (``admitted_command``)."""
    world = locally_qualified
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        pi.launch_owned([str(world.agy)], role=pi.SeatLaunchRole.EXECUTOR_TRUSTED,
                        profile=pi.SeatProfile(env={"PATH": "/usr/bin:/bin"}), cwd=world.tmp)
    assert not world.marker.exists()
    assert world.lookups == []


def test_the_canary_runtime_refuses_a_locally_qualified_image(locally_qualified, monkeypatch):
    """agy_canary_evidence.py:924 (``_trusted_provider_runtime``)."""
    from phase_loop_runtime import agy_canary_evidence

    world = locally_qualified
    account = world.tmp / "account"
    (account / ".local/bin").mkdir(parents=True)
    (account / ".local/bin/agy").write_bytes(world.image)
    (account / ".local/bin/agy").chmod(0o700)
    monkeypatch.setattr(agy_canary_evidence, "_account_home", lambda: account)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        agy_canary_evidence._trusted_provider_runtime("gemini")
    assert world.lookups == []
