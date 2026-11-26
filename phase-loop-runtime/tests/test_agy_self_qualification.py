"""agy first-use self-qualification (agent-harness#1076).

One falsifier per invariant of plans/detailed-agy-selfqual-1076-20260927.md (I1-I6,
D1-D4) and per follow-up the president carried from agent-harness#1118 (claude 5.1-5.8,
section 2, section 3). Each test names the mutation that turns it red.

Nothing here reaches the network or a model: the release listing and archives are
served by an in-memory transport, help measurement and the three live operations are
replaced by counting fakes, and store ownership / machine-id are injected.
"""
from __future__ import annotations

from hashlib import sha256, sha512
import io
import json
import mmap
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tarfile
import textwrap
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

q = pytest.importorskip("phase_loop_runtime.agy_qualification")

from phase_loop_runtime import agy_attestation as att  # noqa: E402
from phase_loop_runtime import agy_provenance as prov  # noqa: E402
from phase_loop_runtime import gemini_heartbeat as gh  # noqa: E402

MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
F_ADD_SEALS, F_GET_SEALS = 1033, 1034
F_SEAL_SEAL, F_SEAL_SHRINK, F_SEAL_GROW, F_SEAL_WRITE, F_SEAL_FUTURE_WRITE = 0x1, 0x2, 0x4, 0x8, 0x10


# ----------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module", autouse=True)
def _module_working_directory():
    """The working directory this module started in; it must be the one it ends in."""
    before = os.getcwd()
    yield before
    after = os.getcwd()
    os.chdir(before)
    assert after == before, f"a test left the working directory at {after}"


@pytest.fixture(autouse=True)
def _working_directory_is_restored(_module_working_directory):
    """No test here may leave the process in another directory: an in-process ``q.worker``
    changes into its authority, and later tests in the same process (other modules too)
    resolve paths from the cwd. Checked as each test starts, when every fixture of the
    previous test, ``monkeypatch`` included, has been torn down."""
    current = os.getcwd()
    if current != _module_working_directory:
        os.chdir(_module_working_directory)
        pytest.fail(f"a previous test left the working directory at {current}")


@pytest.fixture(autouse=True)
def _private_state(tmp_path_factory, monkeypatch):
    """Every test gets its own per-user state home and machine-id (the watch keeps its push
    record in the same operator-only store); ``world`` narrows it further."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("state-home")))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)


class _Answer:
    def __init__(self, status, body):
        self.status, self._body = status, io.BytesIO(body)

    def read(self, n=-1):
        return self._body.read(n)

    def close(self):
        pass


class _ChannelOpener:
    """``agy_attestation``'s opener in every test here, so nothing reaches the network: GitHub
    lists no attestation (404), and the installer manifest names ``manifest_version`` with
    ``package`` as its archive (by default another version, so the second channel says
    ``not_listed``)."""

    def __init__(self):
        self.manifest_version, self.package, self.attestation, self.requests = "0.0.0", b"google package", (404, b""), []

    def open(self, url, *, accept):
        self.requests.append(url)
        parts = urlsplit(url)
        if parts.hostname == prov.API_HOST and "/attestations/" in parts.path:
            return _Answer(*self.attestation)
        if parts.hostname == att.MANIFEST_HOST:
            return _Answer(200, json.dumps({
                "version": self.manifest_version,
                "url": f"{att.MANIFEST_DOWNLOAD_PREFIX}{self.manifest_version}-1/linux-x64/cli_linux_x64.tar.gz",
                "sha512": sha512(self.package).hexdigest()}).encode())
        if parts.hostname == att.PACKAGE_HOST:
            return _Answer(200, self.package)
        raise AssertionError(f"unexpected upstream-channel request {url}")


@pytest.fixture(autouse=True)
def upstream_channel(monkeypatch):
    channel = _ChannelOpener()
    monkeypatch.setattr(att, "_Opener", lambda **_: channel)
    return channel


def _archive(members):
    """A tar.gz of ``members``: (name, bytes | None, type) triples."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = "elsewhere"
            if data is not None:
                info.size = len(data)
            bundle.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


class FakeTransport:
    """The release API and asset downloads, in memory; counts every request."""

    def __init__(self):
        self.releases, self.blobs, self.calls = [], {}, []
        self.fail = None

    def add(self, version, image, *, asset=HOST.asset, archive=None, prerelease=False, draft=False,
            digest=None, url=None):
        archive = archive if archive is not None else _archive([("antigravity", image, tarfile.REGTYPE)])
        url = url or f"{prov.DOWNLOAD_PREFIX}{version}/{asset}"
        self.blobs[url] = archive
        self.releases.insert(0, {
            "tag_name": version, "prerelease": prerelease, "draft": draft,
            "published_at": "2026-11-07T08:38:26Z",
            "assets": [{"name": asset, "browser_download_url": url,
                        "digest": digest or "sha256:" + sha256(archive).hexdigest()}],
        })

    def open(self, url, *, accept):
        self.calls.append(url)
        if self.fail is not None:
            raise self.fail
        if url.startswith(f"https://{prov.API_HOST}/"):
            query = parse_qs(urlsplit(url).query)
            if "per_page" in query:  # the paged listing (PROVFWD-detail §1.2)
                per_page, page = int(query["per_page"][0]), int(query.get("page", ["1"])[0])
                return io.BytesIO(json.dumps(self.releases[(page - 1) * per_page:page * per_page]).encode())
            return io.BytesIO(json.dumps(self.releases).encode())
        return io.BytesIO(self.blobs[url])


class Counter:
    def __init__(self):
        self.help, self.qualify, self.help_bytes, self.qualify_bytes = 0, 0, [], []


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A synthetic agy on PATH, an empty per-user store, a fake upstream and counting fakes."""
    q._HELP_MEMO.clear()
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    image = b"#!/bin/sh\necho synthetic agy 1.2.99\n"
    (bindir / "agy").write_bytes(image)
    (bindir / "agy").chmod(0o755)
    home = tmp_path / "home"
    token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text("synthetic\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {"f" * 64: "e" * 64})
    transport = FakeTransport()
    transport.add("1.2.99", image)
    counter = Counter()

    def fake_help(verified, env):
        counter.help += 1
        fd = verified.reopen()
        try:
            counter.help_bytes.append(os.pread(fd, 1 << 20, 0))
        finally:
            os.close(fd)
        return b"synthetic help\n"

    def fake_qualify(verified, help_bytes, *, cancel_event=None, heartbeat=None, store=None,
                     _store_locked=False):
        counter.qualify += 1
        fd = verified.reopen()
        try:
            counter.qualify_bytes.append(os.pread(fd, 1 << 20, 0))
        finally:
            os.close(fd)
        return world_ns.outcome

    monkeypatch.setattr(q, "_run_help", fake_help)
    monkeypatch.setattr(q, "qualify_image", fake_qualify)
    world_ns = SimpleNamespace(
        tmp=tmp_path, bindir=bindir, agy=bindir / "agy", image=image, digest=sha256(image).hexdigest(),
        env={"PATH": str(bindir), "HOME": str(home)}, token=token, transport=transport, counter=counter,
        outcome={"status": "passed"},
    )
    world_ns.store = lambda **kw: q.Store(**kw)
    return world_ns


_REAL_QUALIFY = q.qualify_image


def _ensure(world, **kwargs):
    kwargs.setdefault("transport", world.transport)
    admission = q.ensure_admitted(world.env, **kwargs)
    try:
        return admission.admission_class, admission.image.sha256, admission.help_sha256
    finally:
        admission.close()


def _admit(world):
    admission = gh.admit(world.env)
    try:
        return admission.admission_class
    finally:
        admission.close()


def _entries(world):
    return q.Store().entries()


# ------------------------------------------------------------------ happy path, I5, D1

def test_first_use_qualifies_once_and_later_lookups_reuse_the_record(world):
    assert _ensure(world) == ("locally_qualified", world.digest, sha256(b"synthetic help\n").hexdigest())
    assert world.counter.qualify == 1
    q._HELP_MEMO.clear()
    assert _admit(world) == "locally_qualified"  # lookup only: a second board, no inference
    assert world.counter.qualify == 1
    assert sorted(_entries(world)) == ["fetch_ledger", "member_cache", "provenance", "qualified"]


def test_a_retired_1_2_11_image_in_window_self_qualifies_on_first_use(world, monkeypatch):
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {
        "b5385638174a5e720e904f3a2678752534fb8414d10c2c302fa16daf56cbcfc9":
            "a12355e8fc064b330eeb25ba52de596406582752442e293083bcda6388a63b78",
    })
    retired = FakeTransport()
    retired.add("1.2.11", world.image)
    assert world.digest not in gh.QUALIFIED_IMAGES
    assert _ensure(world, transport=retired)[0] == "locally_qualified"
    q._HELP_MEMO.clear()
    assert _admit(world) == "locally_qualified"


def test_a_retired_1_2_11_image_outside_the_old_window_is_found_within_the_calls_its_position_needs(
        world, monkeypatch):
    """PROVFWD (EC-PROVFWD-1): no window. Behind four newer releases the image is the fifth
    candidate; each call fetches at most ``DOWNLOAD_BUDGET`` archives and caches their
    members, so the third call admits it. Mutation: restoring a slice of the listing."""
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {
        "b5385638174a5e720e904f3a2678752534fb8414d10c2c302fa16daf56cbcfc9":
            "a12355e8fc064b330eeb25ba52de596406582752442e293083bcda6388a63b78",
    })
    retired = FakeTransport()
    retired.add("1.2.11", world.image)
    for version in ("1.3.5", "1.4.0", "1.5.2", "1.5.3"):
        retired.add(version, f"#!/bin/sh\necho synthetic agy {version}\n".encode())
    for _ in range(2):
        with pytest.raises(ValueError, match=prov.UNVERIFIED):
            _ensure(world, transport=retired)
    assert (world.counter.help, world.counter.qualify) == (0, 0)
    assert _ensure(world, transport=retired)[0] == "locally_qualified"
    downloads = [call for call in retired.calls if "/releases/download/" in call]
    assert len(downloads) == 5 == len(set(downloads))


def test_admission_carries_exactly_one_known_class():
    """I5. Mutation: accepting an unknown class string."""
    image = gh.VerifiedImage.from_bytes(b"x")
    try:
        with pytest.raises(ValueError):
            gh.Admission(image, None, "trusted_because_i_said_so")
        assert gh.ADMISSION_CLASSES == ("release_qualified", "locally_qualified", "qualification_candidate")
    finally:
        image.close()


# ------------------------------------------------------------- I1 before provenance

def test_byte_flipped_image_refuses_before_any_execution(world):
    """I1. Mutation: executing (help) before the member digest matches."""
    world.agy.write_bytes(world.image[:-2] + b"X\n")
    with pytest.raises(ValueError, match=prov.UNVERIFIED):
        _ensure(world)
    assert (world.counter.help, world.counter.qualify) == (0, 0)
    assert "provenance" not in _entries(world) and "qualified" not in _entries(world)


@pytest.mark.parametrize("case", [
    "prerelease", "draft", "other_platform_asset", "musl_asset_on_glibc", "bad_url", "foreign_url",
    "malformed_digest", "uppercase_digest", "archive_digest_mismatch", "member_mismatch",
])
def test_provenance_rejects_every_non_genuine_asset_with_zero_executions(world, case):
    """I1. Mutation: dropping any one asset / URL / digest / member check."""
    t = FakeTransport()
    image = world.image
    if case == "prerelease":
        t.add("1.2.99", image, prerelease=True)
    elif case == "draft":
        t.add("1.2.99", image, draft=True)
    elif case == "other_platform_asset":
        t.add("1.2.99", image, asset="agy_cli_linux_arm64.tar.gz")
    elif case == "musl_asset_on_glibc":
        t.add("1.2.99", image, asset="agy_cli_linux_x64_musl.tar.gz")
    elif case == "bad_url":
        t.add("1.2.99", image, url=f"{prov.DOWNLOAD_PREFIX}1.2.98/{HOST.asset}")
    elif case == "foreign_url":
        t.add("1.2.99", image, url=f"https://github.com/evil/antigravity-cli/releases/download/1.2.99/{HOST.asset}")
    elif case == "malformed_digest":
        t.add("1.2.99", image, digest="sha256:" + "0" * 63)
    elif case == "uppercase_digest":
        archive = _archive([("antigravity", image, tarfile.REGTYPE)])
        t.add("1.2.99", image, archive=archive, digest="sha256:" + sha256(archive).hexdigest().upper())
    elif case == "archive_digest_mismatch":
        t.add("1.2.99", image, digest="sha256:" + "0" * 64)
    elif case == "member_mismatch":
        t.add("1.2.99", image + b"#")
    with pytest.raises(ValueError, match=prov.UNVERIFIED):
        _ensure(world, transport=t)
    assert (world.counter.help, world.counter.qualify) == (0, 0)


@pytest.mark.parametrize("members,ok", [
    ([("antigravity", "IMG", tarfile.REGTYPE)], True),
    ([("./antigravity", "IMG", tarfile.REGTYPE)], True),
    ([("README", b"x", tarfile.REGTYPE), ("antigravity", "IMG", tarfile.REGTYPE)], True),
    ([("antigravity", "IMG", tarfile.REGTYPE), ("./antigravity", "IMG", tarfile.REGTYPE)], False),
    ([("antigravity", None, tarfile.SYMTYPE)], False),
    ([("antigravity", None, tarfile.DIRTYPE)], False),
    ([("antigravity", None, tarfile.LNKTYPE)], False),
    ([("other", "IMG", tarfile.REGTYPE)], False),
])
def test_archive_needs_exactly_one_regular_antigravity_member(world, members, ok):
    """claude 5.8. Mutation: taking the first/last member, or following a link."""
    archive = _archive([(n, world.image if d == "IMG" else d, k) for n, d, k in members])
    asset = prov.ReleaseAsset("1.2.99", HOST.asset, "u", sha256(archive).hexdigest())
    if ok:
        assert prov.read_member(io.BytesIO(archive), asset) == world.digest
    else:
        with pytest.raises(prov.ProvenanceError):
            prov.read_member(io.BytesIO(archive), asset)


def test_member_digest_is_returned_only_after_the_archive_digest_matches(world):
    archive = _archive([("antigravity", world.image, tarfile.REGTYPE)])
    asset = prov.ReleaseAsset("1.2.99", HOST.asset, "u", "0" * 64)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        prov.read_member(io.BytesIO(archive), asset)


# Upstream agy 1.5.11's linux-x64 ``antigravity`` member is 268,841,672 bytes (1.5.12's is
# 269,443,784). A 250 MB member bound refused every in-window release, so self-qualification
# of a genuine current agy always ended ``gemini_heartbeat_provenance_unverified``.
UPSTREAM_MEMBER_BYTES = 268_841_672


def _sparse_member_archive(tmp_path, size):
    """A tar.gz whose ``antigravity`` member is ``size`` bytes, almost all zeros. The member
    is a sparse file and is streamed into the archive, so neither disk nor memory holds it."""
    member = tmp_path / "antigravity"
    with open(member, "wb") as handle:
        handle.write(b"\x7fELF")
        handle.truncate(size)
    digest = sha256()
    with open(member, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    path = tmp_path / HOST.asset
    with tarfile.open(path, "w:gz", compresslevel=1) as bundle:
        bundle.add(member, arcname="antigravity")
    member.unlink()
    return path.read_bytes(), digest.hexdigest()


def test_an_upstream_sized_member_is_verified_and_matched(tmp_path):
    archive, image_sha256 = _sparse_member_archive(tmp_path, UPSTREAM_MEMBER_BYTES)
    assert UPSTREAM_MEMBER_BYTES > 250_000_000 and len(archive) <= prov.MAX_ARCHIVE_BYTES
    asset = prov.ReleaseAsset("1.5.11", HOST.asset, "u", sha256(archive).hexdigest())
    assert prov.read_member(io.BytesIO(archive), asset) == image_sha256
    t = FakeTransport()
    t.add("1.5.11", None, archive=archive)
    found = prov.find_provenance(image_sha256, host=HOST, transport=t)
    assert (found.image_sha256, found.asset.version) == (image_sha256, "1.5.11")


@pytest.mark.parametrize("over", [0, 1])
def test_a_member_over_the_bound_is_refused(world, monkeypatch, over):
    """The bound still holds: a member at the bound is read, one byte over is refused."""
    archive = _archive([("antigravity", world.image, tarfile.REGTYPE)])
    asset = prov.ReleaseAsset("1.2.99", HOST.asset, "u", sha256(archive).hexdigest())
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", len(world.image) - over)
    if over:
        with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
            prov.read_member(io.BytesIO(archive), asset)
    else:
        assert prov.read_member(io.BytesIO(archive), asset) == world.digest


def test_the_member_bound_admits_current_upstream_and_stays_bounded():
    """One bound for the runtime and the release verifier, above current upstream images
    and well below anything that could exhaust memory in the streaming path."""
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image_bound", script)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    assert verifier.MAX_MEMBER_BYTES == prov.MAX_MEMBER_BYTES
    assert 269_443_784 < prov.MAX_MEMBER_BYTES <= 512_000_000


# --------------------------------------------------------------- I1 after verification

def test_path_swap_after_provenance_still_executes_the_verified_bytes(world, monkeypatch):
    """I1 TOCTOU. Mutation: re-opening the PATH file after provenance (a second open)."""
    opens = []
    real_open = gh._open_image_fd
    monkeypatch.setattr(gh, "_open_image_fd", lambda path: opens.append(path) or real_open(path))
    # The seat admission boundary reads the subject itself (AGYFRESH §2.2); count both readers.
    real_read = q._read_subject
    monkeypatch.setattr(q, "_read_subject", lambda path, resolved: opens.append(path) or real_read(path, resolved))
    real_find = prov.find_provenance

    def find_then_swap(*args, **kwargs):
        result = real_find(*args, **kwargs)
        world.agy.write_bytes(b"#!/bin/sh\necho swapped\n")
        return result

    monkeypatch.setattr(prov, "find_provenance", find_then_swap)
    assert _ensure(world)[0] == "locally_qualified"
    assert world.counter.help_bytes == [world.image]
    assert world.counter.qualify_bytes == [world.image]
    assert len(opens) == 1  # exactly one open of the path for this admission


def test_path_swap_after_help_and_after_qualification_executes_the_verified_bytes(world, monkeypatch):
    real_help = q._run_help

    def help_then_swap(verified, env):
        out = real_help(verified, env)
        world.agy.write_bytes(b"#!/bin/sh\necho swapped-after-help\n")
        return out

    monkeypatch.setattr(q, "_run_help", help_then_swap)
    assert _ensure(world)[0] == "locally_qualified"
    assert world.counter.qualify_bytes == [world.image]


def test_cached_admission_then_swap_binds_the_admitted_memfd_into_the_profile(world):
    """I1: a locally_qualified admission is swapped on disk before the leg launches."""
    _ensure(world)
    admission = gh.admit(world.env)
    try:
        world.agy.write_bytes(b"#!/bin/sh\necho swapped-before-leg\n")
        world.env["PATH"] = str(world.tmp)  # and PATH now points elsewhere
        with gh.owned_profile(world.env, settings_bytes=b"{}\n", credential_path=world.token,
                              admission=admission) as profile:
            assert os.pread(profile.image_fd, 1 << 20, 0) == world.image
            assert profile.evidence["provider_image_sha256"] == world.digest
            assert profile.evidence["provider_admission_class"] == "locally_qualified"
    finally:
        admission.close()


def test_expected_digest_comes_from_the_single_read_not_the_checked_bytes(world, monkeypatch):
    """I1. Mutation: VerifiedImage.from_bytes taking its digest from the memfd it checks."""
    real = gh._sealed_tree_fd

    def tampering(*, data, executable, label):
        return real(data=data[:-1] + b"!", executable=executable, label=label)

    monkeypatch.setattr(gh, "_sealed_tree_fd", tampering)
    with pytest.raises(ValueError):
        gh.VerifiedImage.from_bytes(world.image)


def test_versioned_install_symlink_is_resolved_once_to_its_final_target(world):
    target = world.tmp / "versions" / "agy-1.2.99"
    target.parent.mkdir()
    target.write_bytes(world.image)
    target.chmod(0o755)
    world.agy.unlink()
    world.agy.symlink_to(target)
    assert _ensure(world)[1] == world.digest


# ------------------------------------------------------------------- worker fd gate

def _memfd(data, seals):
    fd = os.memfd_create("t", os.MFD_ALLOW_SEALING)
    os.write(fd, data)
    if seals:
        import fcntl
        fcntl.fcntl(fd, F_ADD_SEALS, seals)
    return fd


FULL = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL


@pytest.mark.parametrize("kind", ["unsealed", "no_seal_seal", "no_write", "no_grow", "no_shrink",
                                  "future_write_only_with_live_mapping", "regular_file"])
def test_worker_refuses_any_fd_that_is_not_a_fully_sealed_memfd(world, kind, monkeypatch):
    """Worker bypass. Genuine bytes, a VALID provenance entry, and a write after the hash
    where the fd allows one: zero launches. Mutation: dropping any seal from the mask."""
    monkeypatch.chdir(world.tmp)
    _ensure(world)  # a valid provenance entry for these exact bytes exists
    launches = []
    monkeypatch.setattr(q._panel(), "invoke_board", lambda *a, **k: launches.append(1))
    monkeypatch.setattr(q, "_set_parent_death_signal", lambda: None)
    mapping = None
    if kind == "regular_file":
        fd = os.open(world.agy, os.O_RDONLY)
    elif kind == "future_write_only_with_live_mapping":
        fd = _memfd(world.image, 0)
        mapping = mmap.mmap(fd, len(world.image), mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        import fcntl
        fcntl.fcntl(fd, F_ADD_SEALS, F_SEAL_FUTURE_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL)
    else:
        drop = {"unsealed": FULL, "no_seal_seal": F_SEAL_SEAL, "no_write": F_SEAL_WRITE,
                "no_grow": F_SEAL_GROW, "no_shrink": F_SEAL_SHRINK}[kind]
        fd = _memfd(world.image, FULL & ~drop)
    try:
        with pytest.raises(q.QualificationFailure):
            q.worker(world.tmp, fd, None)
        if mapping is not None:
            mapping[:1] = b"X"  # the live mapping could still have changed the bytes
    finally:
        if mapping is not None:
            mapping.close()
        os.close(fd)
    assert launches == [] and gh._CANDIDATE is None


@pytest.mark.parametrize("launch_class", [None, "board", "unknown"])
def test_worker_requires_its_private_launch_class(monkeypatch, tmp_path, launch_class):
    monkeypatch.setenv("PHASE_LOOP_SEAT_LAUNCH_CLASS", "qualification")
    monkeypatch.setattr(q, "_set_parent_death_signal", lambda: None)
    monkeypatch.setattr(q, "verified_fd_image", lambda fd: SimpleNamespace(sha256="test"))
    monkeypatch.setattr(q, "provenance_gate", lambda sha: True)
    monkeypatch.setattr(q, "_verified_review_authority", lambda authority: tmp_path)
    monkeypatch.setattr(q._panel(), "invoke_board", lambda *a, **kw: pytest.fail("worker launched"))
    with pytest.raises(q.QualificationFailure, match="valid launch class"):
        q.worker(tmp_path, 42, launch_class=launch_class)


def test_worker_refuses_sealed_unverified_bytes_without_provenance(world, monkeypatch):
    monkeypatch.chdir(world.tmp)
    launches = []
    monkeypatch.setattr(q._panel(), "invoke_board", lambda *a, **k: launches.append(1))
    monkeypatch.setattr(q, "_set_parent_death_signal", lambda: None)
    fd = _memfd(b"#!/bin/sh\necho never verified\n", FULL)
    try:
        with pytest.raises(q.QualificationFailure, match="no provenance"):
            q.worker(world.tmp, fd, None)
    finally:
        os.close(fd)
    assert launches == []


@pytest.mark.parametrize("change", ["profile", "operations"])
def test_worker_gate_and_member_cache_are_bound_to_the_profile_digest(world, monkeypatch, change):
    """A live profile/operations change invalidates provenance and the member cache."""
    _ensure(world)
    if change == "profile":
        monkeypatch.setattr(gh, "PROFILE_ID", "agy_memfd_home_deny_all_v2")
    else:
        operation = q.OPERATIONS_CONTRACT[0]._replace(pass_predicate_id="other_predicate")
        monkeypatch.setattr(q, "OPERATIONS_CONTRACT", (operation, *q.OPERATIONS_CONTRACT[1:]))
    assert q.provenance_gate(world.digest) is False
    before = len(world.transport.calls)
    q._HELP_MEMO.clear()
    _ensure(world)
    downloads = [c for c in world.transport.calls[before:] if "releases/download" in c]
    assert downloads, "a runtime change must invalidate the member cache"


def test_fully_sealed_genuine_fd_passes_the_gate(world, monkeypatch):
    _ensure(world)
    fd = _memfd(world.image, FULL)
    try:
        assert q.verified_fd_image(fd).sha256 == world.digest
        assert q.provenance_gate(world.digest) is True
    finally:
        os.close(fd)


def test_release_constant_satisfies_the_gate_with_an_empty_store(world, monkeypatch):
    """claude 5.2 / F050: the manual shim on the pinned build and the watch's prepared tree
    need no provenance entry and never depend on the recency window."""
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {world.digest: "e" * 64})
    assert q.Store().status() == "absent"
    assert q.provenance_gate(world.digest) is True
    assert world.transport.calls == []
    image = q.release_image_from_path(world.env)
    try:
        assert image.sha256 == world.digest
    finally:
        image.close()


def test_manual_shim_path_refuses_a_non_release_image(world):
    with pytest.raises(q.QualificationFailure, match="not a qualified set member"):
        q.release_image_from_path(world.env)


# ------------------------------------------------------- the worker's review authority

def _authority_git(repo, *args):
    return subprocess.run(["/usr/bin/git", "-C", str(repo), "-c", "user.name=Fixture",
                           "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True).stdout


def _operation_root(tmp_path, name="completion"):
    root = tmp_path / name
    root.mkdir(mode=0o700)
    (root / "artifact.md").write_text("synthetic qualification artifact\n")
    (root / "brief.md").write_text("synthetic qualification brief\n")
    return root


@pytest.fixture
def authority_base(tmp_path, monkeypatch):
    """A private parent for the authorities a test creates (the production candidates are
    the store's private area, then /tmp; their selection has its own tests)."""
    base = tmp_path / "authorities"
    base.mkdir(mode=0o700)
    monkeypatch.setattr(q, "_authority_bases", lambda: [base])
    return base.resolve()


@pytest.fixture
def worker_process(monkeypatch, tmp_path):
    """``q.worker`` run in-process: no PDEATHSIG on the test runner, its candidate, the
    SIGTERM/SIGINT handlers it installs and the working directory restored afterwards."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(q, "_set_parent_death_signal", lambda: None)
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


def _capture_board(monkeypatch, *, staged=None, status="OK"):
    calls = []
    staged = q._AUTHORITY_MANIFEST_SHA256 if staged is None else staged

    def invoke_board(board, artifact, **kwargs):
        calls.append({**kwargs, "cwd": Path.cwd()})
        leg = SimpleNamespace(review_monitoring={}, harden_isolation_evidence={},
                              sandbox_placement_evidence={} if staged == "absent" else {"sandbox_snapshot_sha256": staged},
                              status=status, text="AGREE" if status == "OK" else "", detail=None)
        return SimpleNamespace(legs=(leg,))

    monkeypatch.setattr(q._panel(), "invoke_board", invoke_board)
    return calls


def _run_worker(world, monkeypatch, root, authority):
    monkeypatch.setattr(q, "provenance_gate", lambda *a, **k: True)
    fd = _memfd(world.image, FULL)
    try:
        q.worker(root, fd, None, authority, "qualification")
    finally:
        os.close(fd)


def test_the_authority_repository_is_the_pinned_constant(tmp_path, authority_base):
    """The pinned object ids are the SHA-1 of the constant objects (computed here without
    git), git reports the same ones, the repository is fsck-clean, and two creations give
    distinct private directories holding the identical repository."""
    import hashlib

    from phase_loop_runtime import review_stage

    objects = q._authority_objects()
    assert {hashlib.sha1(raw).hexdigest() for raw in objects.values()} == set(objects)
    assert set(objects) == {q._AUTHORITY_BLOB, q._AUTHORITY_TREE, q._AUTHORITY_COMMIT}
    old = os.umask(0o022)
    try:
        first, second = q._create_review_authority(), q._create_review_authority()
    finally:
        os.umask(old)
    try:
        assert first != second and first.parent == second.parent == authority_base
        for authority in (first, second):
            assert stat.S_IMODE(authority.stat().st_mode) == 0o700
            assert _authority_git(authority, "rev-parse", "HEAD").decode().strip() == q._AUTHORITY_COMMIT
            assert _authority_git(authority, "for-each-ref", "--format=%(refname)").decode() == "refs/heads/qualification\n"
            assert _authority_git(authority, "log", "--format=%H %an <%ae> %at %ct %s").decode() == (
                f"{q._AUTHORITY_COMMIT} phase-loop <qualification@invalid> 946684800 946684800 qualification authority\n")
            assert _authority_git(authority, "fsck", "--strict", "--no-dangling") == b""
            assert review_stage.review_tree_manifest_sha256(authority) == q._AUTHORITY_MANIFEST_SHA256
            assert q._verified_review_authority(str(authority)) == authority
    finally:
        q._remove_review_authority(first)
        q._remove_review_authority(second)
    assert not first.exists() and not second.exists()


def test_worker_reviews_the_coordinators_authority_from_a_non_git_cwd(world, monkeypatch, worker_process,
                                                                        authority_base):
    """The board's review authority is the coordinator's, never the inherited cwd, and never
    a governed ``canonical_repo_authority``. Mutations: restoring ``repo_dir=Path.cwd()``
    without the chdir, passing ``canonical_repo_authority``, dropping the chdir."""
    plain = world.tmp / "not-a-repo"
    plain.mkdir()
    monkeypatch.chdir(plain)
    root = _operation_root(world.tmp)
    authority = q._create_review_authority()
    calls = _capture_board(monkeypatch)
    _run_worker(world, monkeypatch, root, str(authority))
    call, = calls
    assert call["repo_dir"] == authority
    assert "canonical_repo_authority" not in call
    assert call["cwd"] == authority
    assert json.loads((root / "terminal.json").read_text())["result"]["status"] == "OK"


def _plant(how, authority, monkeypatch):
    """Change a created authority one way; returns the path the worker is then given."""
    git_dir = authority / ".git"
    if how == "missing":
        q._remove_review_authority(authority)
    elif how == "absent":
        return None
    elif how == "relative":
        return os.path.relpath(authority)
    elif how == "alias":
        alias = authority.parent.parent / "alias"
        alias.symlink_to(authority.parent)
        return str(alias / authority.name)
    elif how == "mode":
        authority.chmod(0o750)
    elif how == "symlink":
        moved = authority.with_name(authority.name + "-moved")
        authority.rename(moved)
        authority.symlink_to(moved)
    elif how == "dotdot":
        return f"{authority.parent}/../{authority.parent.name}/{authority.name}"
    elif how == "foreign_owner":
        # Only the authority directory reports another owner (a chown needs root).
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if os.fspath(path) == str(authority):
                fields = list(info[:10])
                fields[4] = info.st_uid + 1
                return os.stat_result(fields)
            return info

        monkeypatch.setattr(q.os, "lstat", lstat)
    elif how == "unsafe_ancestor":
        authority.parent.chmod(0o770)
    elif how == "ancestor":
        # Its own repository replaced by an inert ``.git`` directory; the parent tracks it.
        subprocess.run(["rm", "-rf", str(git_dir)], check=True)
        _authority_git(authority.parent, "init", "-q")
        _authority_git(authority.parent, "add", f"{authority.name}/QUALIFICATION")
        _authority_git(authority.parent, "commit", "-q", "-m", "ancestor")
        git_dir.mkdir(mode=0o700)
    elif how == "extra_tracked":
        (authority / "EXTRA").write_text("extra\n")
        _authority_git(authority, "add", "EXTRA")
        _authority_git(authority, "commit", "-q", "-m", "extra")
    elif how == "extra_index_entry":
        (authority / "EXTRA").write_text("extra\n")
        _authority_git(authority, "add", "EXTRA")
        (authority / "EXTRA").unlink()
    elif how == "nothing_tracked":
        _authority_git(authority, "rm", "-q", "--cached", "QUALIFICATION")
    elif how == "untracked":
        (authority / "EXTRA").write_text("extra\n")
    elif how == "content":
        (authority / "QUALIFICATION").write_text("changed\n")
    elif how == "executable":
        (authority / "QUALIFICATION").chmod(0o700)
    elif how == "file_symlink":
        target = authority.parent / "target"
        target.write_bytes((authority / "QUALIFICATION").read_bytes())
        (authority / "QUALIFICATION").unlink()
        (authority / "QUALIFICATION").symlink_to(target)
    elif how == "history":
        # A marker committed and then deleted
        # leaves the worktree, index and listing exactly as created, but the staged clone
        # would carry the marker in its history.
        (authority / "MARKER").write_text("synthetic marker\n")
        _authority_git(authority, "add", "MARKER")
        _authority_git(authority, "commit", "-q", "-m", "marker")
        _authority_git(authority, "rm", "-q", "MARKER")
        _authority_git(authority, "commit", "-q", "-m", "drop marker")
    elif how in ("extra_branch", "tag", "stash", "replace"):
        ref = {"extra_branch": "refs/heads/other", "tag": "refs/tags/v0",
               "stash": "refs/stash", "replace": f"refs/replace/{q._AUTHORITY_BLOB}"}[how]
        _authority_git(authority, "update-ref", ref, q._AUTHORITY_COMMIT if how != "replace" else q._AUTHORITY_BLOB)
    elif how == "packed_refs":
        _authority_git(authority, "pack-refs", "--all")
    elif how == "pack":
        _authority_git(authority, "repack", "-a", "-q")
    elif how == "alternates":
        other = authority.parent / "other.git"
        _authority_git(authority.parent, "init", "-q", "--bare", str(other))
        (git_dir / "objects/info/alternates").write_text(str(other / "objects") + "\n")
    elif how == "shallow":
        (git_dir / "shallow").write_text(q._AUTHORITY_COMMIT + "\n")
    elif how == "grafts":
        (git_dir / "info").mkdir()
        (git_dir / "info/grafts").write_text(q._AUTHORITY_COMMIT + "\n")
    elif how == "head":
        _authority_git(authority, "symbolic-ref", "HEAD", "refs/heads/other")
    elif how == "config":
        with (git_dir / "config").open("a") as handle:
            handle.write("[core]\n\tworktree = /\n")
    elif how == "forged_object":
        import zlib

        path = git_dir / "objects" / q._AUTHORITY_BLOB[:2] / q._AUTHORITY_BLOB[2:]
        path.chmod(0o600)
        path.write_bytes(zlib.compress(b"blob 8\0changed\n"))
    return str(authority)


AUTHORITY_PLANTS = ["missing", "absent", "relative", "alias", "dotdot", "mode", "symlink", "foreign_owner",
                    "unsafe_ancestor", "ancestor", "extra_tracked", "extra_index_entry",
                    "nothing_tracked", "untracked", "content", "executable", "file_symlink", "history",
                    "extra_branch", "tag", "stash", "replace", "packed_refs", "pack", "alternates",
                    "shallow", "grafts", "head", "config", "forged_object"]


@pytest.mark.parametrize("how", AUTHORITY_PLANTS)
def test_worker_refuses_an_authority_it_cannot_prove_private(world, monkeypatch, worker_process,
                                                             authority_base, how):
    """Each check fails closed before any board runs: the placement (absolute, canonical,
    0700, this euid, private ancestry), the exact layout and contents (pinned objects, one
    ref, no packs, alternates, grafts or shallow state), the toplevel and the index."""
    monkeypatch.chdir(world.tmp)
    root = _operation_root(world.tmp)
    authority = q._create_review_authority()
    given = _plant(how, authority, monkeypatch)
    calls = _capture_board(monkeypatch)
    try:
        with pytest.raises(q.QualificationFailure, match="review authority is not private"):
            _run_worker(world, monkeypatch, root, given)
    finally:
        authority.parent.chmod(0o700)
    assert calls == [] and gh._CANDIDATE is None
    assert not (root / "terminal.json").exists()


def test_a_marker_in_earlier_history_is_refused(authority_base):
    """After a marker is committed and then deleted, the
    top-level listing, the index and the placeholder are as created, yet HEAD and the object
    store are not the pinned repository, so the verifier refuses it."""
    authority = q._create_review_authority()
    _plant("history", authority, None)
    assert sorted(os.listdir(authority)) == [".git", "QUALIFICATION"]
    assert _authority_git(authority, "ls-files", "-z") == b"QUALIFICATION\0"
    assert (authority / "QUALIFICATION").read_bytes() == q._AUTHORITY_BYTES
    assert _authority_git(authority, "show", "HEAD~1:MARKER") == b"synthetic marker\n"
    with pytest.raises(q.QualificationFailure, match="review authority is not private"):
        q._verified_review_authority(str(authority))


def test_a_sticky_shared_parent_is_private_enough(authority_base):
    """A world-writable parent is acceptable only when sticky (the /tmp case): no other uid
    can rename this uid's entry in it."""
    authority = q._create_review_authority()
    authority_base.chmod(0o1777)
    try:
        assert q._verified_review_authority(str(authority)) == authority
        authority_base.chmod(0o777)
        with pytest.raises(q.QualificationFailure):
            q._verified_review_authority(str(authority))
    finally:
        authority_base.chmod(0o700)


def test_private_ancestry_rule(tmp_path):
    euid = os.geteuid()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    assert q._private_ancestry(private.resolve(), euid) is True
    assert q._private_ancestry(private.resolve(), euid + 1) is False  # owned by another uid
    for mode, expected in ((0o750, True), (0o770, False), (0o702, False), (0o1777, True), (0o1770, True)):
        private.chmod(mode)
        assert q._private_ancestry(private.resolve(), euid) is expected, oct(mode)
    private.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(private)
    assert q._private_ancestry(link, euid) is False  # a symlink is not a directory


def test_the_authority_prefers_the_stores_private_area(world):
    """With a safe store, authorities live in its private ``authority`` directory; never under
    an operation's (possibly operator-chosen) output root."""
    store = q.Store()
    store.create()
    assert q._authority_bases()[0] == store.root / "authority"
    authority = q._create_review_authority()
    try:
        assert authority.parent == (store.root / "authority").resolve()
        assert stat.S_IMODE(authority.parent.stat().st_mode) == 0o700
        assert store.status() == "ok"
    finally:
        q._remove_review_authority(authority)


def test_without_a_safe_store_the_authority_parent_is_tmp(world, monkeypatch):
    assert q.Store().status() == "absent"
    assert q._authority_bases() == [Path("/tmp")]
    if q._private_ancestry(Path("/tmp").resolve(), os.geteuid()):
        assert q._authority_parent() == Path("/tmp").resolve()


def test_an_unsafe_candidate_is_skipped_and_none_left_is_a_local_failure(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o700)
    shared.chmod(0o770)
    private = tmp_path / "private"
    monkeypatch.setattr(q, "_authority_bases", lambda: [shared, private])
    assert q._authority_parent() == private.resolve()
    assert stat.S_IMODE(private.stat().st_mode) == 0o700  # created when absent
    monkeypatch.setattr(q, "_authority_bases", lambda: [shared])
    with pytest.raises(q.QualificationFailure, match=q.LOCAL_FAILURE):
        q._create_review_authority()
    assert list(shared.iterdir()) == []


ESCAPES = ["%20", "%25", "%2F"]


def _decoy(tmp_path, escape):
    """The path git would decode ``qual<escape>state`` to, with a store-shaped decoy."""
    decoded = tmp_path / {"%20": "qual state", "%25": "qual%state", "%2F": "qual/state"}[escape]
    (decoded / "phase-loop/agy-qualification/authority").mkdir(parents=True)
    return decoded


@pytest.mark.parametrize("escape", ESCAPES)
def test_a_store_path_git_would_url_decode_is_never_used(tmp_path, monkeypatch, escape):
    """The board clones ``file://<authority>`` and git decodes ``%XX``
    escapes there, so a store under a literal ``qual%20state`` would be verified at one path
    and staged from another. Such a store is skipped for /tmp (or, with no private /tmp,
    creation refuses); no authority path ever holds a ``%``, and the decoded path is untouched."""
    state = tmp_path / f"qual{escape}state"
    state.mkdir(mode=0o700)
    decoy = _decoy(tmp_path, escape)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    store = q.Store()
    store.create()
    assert q._authority_bases()[0] == store.root / "authority"
    if q._private_ancestry(Path("/tmp").resolve(), os.geteuid()):
        authority = q._create_review_authority()
        try:
            assert authority.parent == Path("/tmp").resolve() and "%" not in str(authority)
            assert q._verified_review_authority(str(authority)) == authority
        finally:
            q._remove_review_authority(authority)
    else:
        with pytest.raises(q.QualificationFailure, match=q.LOCAL_FAILURE):
            q._create_review_authority()
    assert not (store.root / "authority").exists(), "nothing is created under an escaped path"
    assert list((decoy / "phase-loop/agy-qualification/authority").iterdir()) == []


@pytest.mark.parametrize("escape", ESCAPES)
def test_a_candidate_that_resolves_to_a_percent_escape_is_skipped(tmp_path, monkeypatch, escape):
    """The check applies to the resolved path too: a candidate spelled without ``%`` that
    resolves through a symlink to a path holding one is skipped for the next candidate."""
    target = tmp_path / f"real{escape}dir"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target)
    safe = tmp_path / "safe"
    monkeypatch.setattr(q, "_authority_bases", lambda: [link, safe])
    assert q._authority_parent() == safe.resolve()


@pytest.mark.parametrize("escape", ESCAPES)
def test_coordinator_and_worker_refuse_an_authority_path_with_a_percent_escape(
        world, monkeypatch, authority_base, escape):
    """The final path is re-checked on both sides: the worker's verifier and the proof the
    coordinator runs on its own creation refuse an otherwise exact authority whose path
    holds an escape. A run whose only candidate parent holds one fails closed at stage
    ``authority`` as a local failure, before any launch."""
    authority = q._create_review_authority()
    escaped = world.tmp / f"moved{escape}here"
    escaped.mkdir(mode=0o700)
    moved = escaped / authority.name
    authority.rename(moved)
    with pytest.raises(q.QualificationFailure, match="review authority is not private"):
        q._verified_review_authority(str(moved))
    assert q._authority_proven(moved) is False
    help_path, help_sha256 = _operation_inputs(world, monkeypatch)
    monkeypatch.setattr(q, "_authority_bases", lambda: [escaped])
    launches = []
    monkeypatch.setattr(q._panel(), "launch_provider", lambda *a, **k: launches.append(1))
    root = world.tmp / "completion"
    image = gh.VerifiedImage.from_bytes(world.image)
    try:
        with pytest.raises(q.QualificationFailure, match=q.LOCAL_FAILURE):
            q.run_operation("completion", root, help_path, image=image, expected_help_sha256=help_sha256)
    finally:
        image.close()
    failure = json.loads((root / "failure.json").read_text())
    assert (failure["stage"], failure["reason"]) == ("authority", q.LOCAL_FAILURE)
    assert launches == [] and sorted(p.name for p in escaped.iterdir()) == [moved.name]


def test_an_in_process_worker_returns_to_the_callers_directory(world, monkeypatch, authority_base):
    """The worker changes into its authority for the board and returns to the directory it
    was called from, after a board that passed and after one its post-check refused. No
    ``monkeypatch.chdir`` here: the worker's own restore is what is tested. Mutation:
    dropping the restore leaves the process in the authority."""
    monkeypatch.setattr(q, "_set_parent_death_signal", lambda: None)
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    before = os.getcwd()
    try:
        for staged in (None, "0" * 64):
            root = _operation_root(world.tmp, "ok" if staged is None else "refused")
            authority = q._create_review_authority()
            calls = _capture_board(monkeypatch, staged=staged)
            if staged is None:
                _run_worker(world, monkeypatch, root, str(authority))
            else:
                with pytest.raises(q.QualificationFailure, match="staged review tree differs"):
                    _run_worker(world, monkeypatch, root, str(authority))
            assert calls[0]["cwd"] == authority
            assert os.getcwd() == before
    finally:
        os.chdir(before)
        for sig, handler in saved.items():
            signal.signal(sig, handler)


@pytest.mark.parametrize("staged,status,refused", [
    ("pinned", "OK", False), ("0" * 64, "OK", True), ("absent", "OK", True),
    ("absent", "UNAVAILABLE", False), ("0" * 64, "UNAVAILABLE", True),
])
def test_the_worker_binds_the_staged_tree_to_the_verified_authority(world, monkeypatch, worker_process,
                                                                   authority_base, staged, status, refused):
    """After the board: the staged-tree manifest it authorized and revalidated must be the
    authority's constant manifest. A refusal before any staging keeps its terminal record."""
    root = _operation_root(world.tmp)
    authority = q._create_review_authority()
    _capture_board(monkeypatch, staged=None if staged == "pinned" else staged, status=status)
    if refused:
        with pytest.raises(q.QualificationFailure, match="staged review tree differs"):
            _run_worker(world, monkeypatch, root, str(authority))
        assert not (root / "terminal.json").exists()
    else:
        _run_worker(world, monkeypatch, root, str(authority))
        assert json.loads((root / "terminal.json").read_text())["result"]["status"] == status


# ------------------------------------------ run_operation: authority stage and diagnostic

def _operation_inputs(world, monkeypatch):
    monkeypatch.setenv("HOME", world.env["HOME"])
    monkeypatch.setattr(q, "helper_pins", lambda extra=(): {})
    help_path = world.tmp / "agy-help.txt"
    help_path.write_bytes(b"synthetic help\n")
    return help_path, sha256(b"synthetic help\n").hexdigest()


def test_a_creation_the_verifier_refuses_is_a_local_failure_that_leaves_nothing(authority_base, monkeypatch):
    """The coordinator proves its own creation with the worker's verifier before launching."""
    monkeypatch.setattr(q, "_authority_proven", lambda authority: False)
    with pytest.raises(q.QualificationFailure, match=q.LOCAL_FAILURE):
        q._create_review_authority()
    assert list(authority_base.iterdir()) == []


def test_an_authority_creation_failure_is_a_local_failure_at_its_own_stage(world, monkeypatch, authority_base):
    """A creation error never launches the worker and leaves nothing behind; it is recorded
    at stage ``authority`` as the local-failure transient."""
    from phase_loop_runtime import review_stage

    help_path, help_sha256 = _operation_inputs(world, monkeypatch)
    launches = []
    monkeypatch.setattr(q._panel(), "launch_provider", lambda *a, **k: launches.append(1))

    def refused(*args, **kwargs):
        raise ValueError("host_helper_unavailable")

    monkeypatch.setattr(review_stage, "host_git", refused)
    root = world.tmp / "completion"
    image = gh.VerifiedImage.from_bytes(world.image)
    try:
        with pytest.raises(q.QualificationFailure, match=q.LOCAL_FAILURE):
            q.run_operation("completion", root, help_path, image=image, expected_help_sha256=help_sha256)
    finally:
        image.close()
    failure = json.loads((root / "failure.json").read_text())
    assert (failure["stage"], failure["reason"]) == ("authority", q.LOCAL_FAILURE)
    assert "worker_terminal" not in failure
    assert launches == [] and list(authority_base.iterdir()) == []
    assert q._classify_failure(root, "completion") == "transient"


@pytest.mark.parametrize("terminal", ["refusal", "absent", "malformed"])
def test_an_unobserved_worker_copies_only_its_terminal_status_and_detail(world, monkeypatch, authority_base, terminal):
    """4.4 diagnostic. The worker got a proven authority outside the operation root (checked
    at launch) and ended before any provider was observed: ``failure.json`` names the
    board's refusal through ``worker_terminal`` = ``{status, detail}``, never ``text``; the
    verdict is unchanged, and the authority is removed afterwards."""
    help_path, help_sha256 = _operation_inputs(world, monkeypatch)
    root = world.tmp / "completion"
    detail = "broker canonical repository authority is not probeable"
    written = {"refusal": json.dumps({"monitoring": None, "broker": None, "result": {
                   "status": "UNAVAILABLE", "text": "PRIVATE_FIXTURE_SENTINEL", "detail": detail}}),
               "absent": None, "malformed": "{"}[terminal]
    proven = []

    def launch(argv, **kwargs):
        given = argv[argv.index("--authority") + 1]
        proven.append(q._verified_review_authority(given))
        script = "" if written is None else (
            f"from pathlib import Path; Path({str(root / 'terminal.json')!r}).write_text({written!r})")
        return subprocess.Popen([sys.executable, "-I", "-c", script], stdout=kwargs.get("stdout"),
                                stderr=kwargs.get("stderr"), start_new_session=True)

    monkeypatch.setattr(q._panel(), "launch_provider", launch)
    image = gh.VerifiedImage.from_bytes(world.image)
    try:
        with pytest.raises(q.QualificationFailure, match=q.ENDED_BEFORE_ADMISSION):
            q.run_operation("completion", root, help_path, image=image, expected_help_sha256=help_sha256)
    finally:
        image.close()
    authority, = proven
    assert authority.parent == authority_base and root not in authority.parents
    assert not authority.exists(), "the operation's authority outlived it"
    failure = json.loads((root / "failure.json").read_text())
    assert failure["stage"] == "terminal_observation"
    if terminal == "refusal":
        assert failure["worker_terminal"] == {"status": "UNAVAILABLE", "detail": detail}
    else:
        assert "worker_terminal" not in failure
    assert "PRIVATE_FIXTURE_SENTINEL" not in (root / "failure.json").read_text()
    assert q._classify_failure(root, "completion") == "transient"


# ---------------------------------------- the real repository gates, no provider (4.5.2)

@pytest.mark.parametrize("shape", ["one_file", "init_only", "empty_commit"])
def test_the_created_authority_clears_the_real_gates_through_broker_construction(tmp_path, monkeypatch,
                                                                                authority_base, shape):
    """From a non-git cwd: the real authority resolution, authorization, activation, local
    stage, revalidations, leg authorization and ``ParentUnixBroker`` construction. The
    created authority is accepted with QUALIFICATION as its probe file, and the authorized
    staged-tree digest is the pinned manifest. Mutation: an authority with zero tracked
    files reproduces the broker refusal seen in production."""
    from dataclasses import replace

    from phase_loop_runtime import review_stage, sandbox_placement
    from phase_loop_runtime.advisor_board import backing
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    panel = q._panel()
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    monkeypatch.chdir(plain)
    if panel._outside_any_git_work_tree(plain):
        # The first production refusal: the cwd as the authority.
        with pytest.raises(ValueError, match="no canonical repository authority"):
            panel._resolve_review_authority(None, Path.cwd(), governed=False)
    if shape == "one_file":
        authority = q._create_review_authority()
    else:
        authority = authority_base / "empty"
        authority.mkdir(mode=0o700)
        _authority_git(authority, "init", "-q")
        if shape == "empty_commit":
            _authority_git(authority, "commit", "-q", "--allow-empty", "-m", "empty")
    board = replace(DEFAULT_BOARD, name="gemini-heartbeat-qualification",
                    seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness == "gemini"))
    seat, = board.seats
    model = backing.harden_subscription_model(seat.harness, seat.model, seat.effort)
    artifact, brief = "synthetic qualification artifact\n", "synthetic qualification brief\n"
    token = backing.set_review_instruction_digest(brief)
    auth = broker = prepared = None
    try:
        resolved = panel._resolve_review_authority(None, authority, governed=False)
        assert resolved == authority.resolve()
        auth = backing.prepare_review_isolation_authorization(
            board, artifact, mode="review", canonical_repo_authority=resolved,
            monitoring_policy="heartbeat_only")
        assert auth.staged_tree_sha256 is not None
        if shape == "one_file":
            assert auth.staged_tree_sha256 == q._AUTHORITY_MANIFEST_SHA256
        backing.activate_review_isolation_authorization(
            auth, board, artifact, mode="review", canonical_repo_authority=resolved)
        leg_base = tmp_path / "pl-panel-leg"
        review_dir = leg_base / "review"
        review_dir.mkdir(parents=True)
        for name, content in (("review-bundle.md", artifact), ("review-instructions.md", brief)):
            (review_dir / name).write_text(content)
            (review_dir / name).chmod(0o400)
        prepared = sandbox_placement.prepare_local_stage(resolved, review_dir, floor_bytes=0, mark=leg_base)
        backing._revalidate_staged_tree(auth, review_dir)
        backing.revalidate_review_isolation_authorization(
            auth, None, artifact, mode="review", staged_dir=review_dir, canonical_repo_authority=resolved)
        leg = backing.derive_review_leg_authorization(
            auth, artifact, harness=seat.harness, model=model, deadline_s=None, mode="review",
            canonical_repo_authority=resolved)
        if shape != "one_file":
            with pytest.raises(ValueError, match="broker canonical repository authority is not probeable"):
                backing.ParentUnixBroker(leg, harness=seat.harness, model=model,
                                         staged_dir=review_dir, canonical_repo=resolved)
            return
        broker = backing.ParentUnixBroker(leg, harness=seat.harness, model=model,
                                          staged_dir=review_dir, canonical_repo=resolved)
        assert broker._canonical_probe_file == authority / "QUALIFICATION"
        assert sorted(path.name for path in prepared.local_tree.iterdir() if path.name != ".git") == ["QUALIFICATION"]
        # The stage's history is the pinned single commit and nothing else.
        assert _authority_git(prepared.local_tree, "rev-list", "--all").decode() == q._AUTHORITY_COMMIT + "\n"
    finally:
        if broker is not None:
            broker.close()
        if prepared is not None:
            review_stage.remove_review_stage(prepared.local_tree)
        if auth is not None:
            backing.close_review_isolation_authorization(auth)
        backing.reset_review_instruction_digest(token)
        q._remove_review_authority(authority)


# ------------------------------------------------------------------------- two-phase

def test_first_use_executes_nothing_before_a_help_free_provenance_entry_exists(world, monkeypatch):
    """Two-phase order. Mutation: measuring help (executing) before the provenance entry."""
    seen = {}
    real_help = q._run_help

    def observing_help(verified, env):
        store = q.Store()
        seen["entries_at_first_exec"] = store.entries()
        (entry,) = [p for p in store.host_dir.iterdir() if p.name.startswith("provenance-")]
        seen["provenance_payload"] = json.loads(entry.read_text())["payload"]
        return real_help(verified, env)

    monkeypatch.setattr(q, "_run_help", observing_help)
    _ensure(world)
    assert "provenance" in seen["entries_at_first_exec"]
    assert "qualified" not in seen["entries_at_first_exec"]
    assert "help_sha256" not in json.dumps(seen["provenance_payload"])


def test_qualified_entry_is_written_only_after_all_three_operations_pass(world):
    world.outcome = {"status": "transient", "operation": "cancel"}
    with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_UNAVAILABLE):
        _ensure(world)
    assert "qualified" not in _entries(world) and "failed" not in _entries(world)


# --------------------------------------------------------------------------- offline

def test_offline_first_use_refuses_and_writes_nothing(world):
    world.transport.fail = OSError("offline")
    with pytest.raises(ValueError, match=prov.UNAVAILABLE):
        _ensure(world)
    assert (world.counter.help, world.counter.qualify) == (0, 0)
    assert "provenance" not in _entries(world)


def test_release_image_is_admitted_offline_without_config_store_or_network(world, monkeypatch):
    """I6/offline. Mutation: consulting config, store or network before the release match."""
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {world.digest: "e" * 64})
    world.transport.fail = AssertionError("network touched")
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: pytest.fail("config read"))
    monkeypatch.setattr(q, "Store", lambda *a, **k: pytest.fail("store read"))
    # Keeping the admitted image afterwards is the HOLD cache's (tests/test_agy_hold_cache.py);
    # this test pins the admission itself, which reads nothing before the release match.
    monkeypatch.setattr(q, "_retain_admitted", lambda *a, **k: None)
    assert _ensure(world)[0] == "release_qualified"
    assert world.transport.calls == []


def test_release_image_reports_release_qualified_even_with_a_local_record(world, monkeypatch):
    _ensure(world)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {world.digest: "e" * 64})
    assert _admit(world) == "release_qualified"


def test_recorded_image_is_admitted_with_zero_network_calls(world):
    _ensure(world)
    world.transport.calls.clear()
    world.transport.fail = AssertionError("network touched")
    q._HELP_MEMO.clear()
    assert _ensure(world)[0] == "locally_qualified"
    assert world.transport.calls == []


# ----------------------------------------------------------------- I4 record / store

def _tamper(world, how):
    store = q.Store()
    host = store.host_dir
    entries = sorted(p for p in host.iterdir() if p.name.startswith(("qualified-", "provenance-")))
    if how == "flipped_byte":
        for path in entries:
            raw = bytearray(path.read_bytes())
            raw[-5] ^= 1
            path.write_bytes(bytes(raw))
    elif how == "file_0644":
        for path in entries:
            path.chmod(0o644)
    elif how == "dir_0755":
        host.chmod(0o755)
    elif how == "root_0755":
        store.root.chmod(0o755)
    elif how == "symlinked_entry":
        for path in entries:
            moved = path.with_name("real-" + path.name)
            path.rename(moved)
            path.symlink_to(moved)
    elif how == "symlinked_store":
        real = store.root.with_name("real-store")
        store.root.rename(real)
        store.root.symlink_to(real)
    elif how == "unknown_schema":
        for path in entries:
            raw = json.loads(path.read_text())
            raw["schema"] = "agy_qualification_entry.v0"
            path.write_text(json.dumps(raw))
    elif how == "short_key":
        (host / "key").write_bytes(b"k")


@pytest.mark.parametrize("how", ["flipped_byte", "file_0644", "dir_0755", "root_0755", "symlinked_entry",
                                 "symlinked_store", "unknown_schema", "short_key"])
def test_tampered_or_loose_store_is_absent_with_zero_executions(world, how):
    """I4 + claude 5.1: every entry-level rejection is 'absent' AND zero executions,
    help measurement included. Mutation: measuring help before the provenance entry verifies."""
    _ensure(world)
    world.counter.help = 0
    q._HELP_MEMO.clear()
    _tamper(world, how)
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        _admit(world)
    assert world.counter.help == 0


@pytest.mark.parametrize("how", ["file_0644", "dir_0755", "symlinked_store", "short_key"])
def test_first_use_refuses_on_a_loose_or_foreign_store_before_provenance(world, how):
    """claude 5.4: never qualify into a store lookups would ignore."""
    _ensure(world)
    for entry in q.Store().host_dir.glob("*.json"):
        entry.unlink()
    if how == "file_0644":
        (q.Store().host_dir / "key").chmod(0o644)
    else:
        _tamper(world, how)
    world.transport.calls.clear()
    with pytest.raises(ValueError, match=q.STORE_UNSAFE):
        _ensure(world)
    assert world.transport.calls == [] and world.counter.help == 1


def test_foreign_owner_is_absent(world):
    _ensure(world)
    q._HELP_MEMO.clear()
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        q.lookup(world.env, world.image, str(world.agy), store=q.Store(euid=os.geteuid() + 1))


def test_store_copied_from_another_host_is_absent(world, monkeypatch):
    _ensure(world)
    q._HELP_MEMO.clear()
    other = "b" * 32
    src = q.Store().host_dir
    dst = q.Store(machine_id=other).host_dir
    dst.mkdir(mode=0o700)
    for path in src.iterdir():
        if not path.is_file():
            continue  # held/, the HOLD cache, is a directory of images, not an entry
        (dst / path.name).write_bytes(path.read_bytes())
        (dst / path.name).chmod(0o600)
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": other)
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        _admit(world)
    assert world.counter.help == 1  # only the original first use ever executed


def test_whole_store_copied_to_another_user_is_absent(world):
    """Key included, ownership and modes valid for the new user: the euid is in every
    MAC context. Mutation: dropping euid from the context."""
    _ensure(world)
    q._HELP_MEMO.clear()
    other = q.Store(euid=os.geteuid() + 1)
    other._lstat = lambda p: _as_uid(os.lstat(p), other.euid)
    other._fstat = lambda fd: _as_uid(os.fstat(fd), other.euid)
    assert other.status() == "ok"
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        q.lookup(world.env, world.image, str(world.agy), store=other)
    assert world.counter.help == 1


def _as_uid(info, uid):
    fields = list(info)
    fields[stat.ST_UID] = uid
    return os.stat_result(fields)


def test_hosts_sharing_a_state_home_are_namespaced_by_machine_id(world):
    """claude 5.4: a shared (NFS) $XDG_STATE_HOME never mixes hosts' entries."""
    a, b = q.Store(machine_id="a" * 32), q.Store(machine_id="b" * 32)
    assert a.host_dir != b.host_dir and a.host_dir.parent == b.host_dir.parent


def test_missing_machine_id_refuses_self_qualification_but_not_release(world, monkeypatch):
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": None)
    with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_UNAVAILABLE):
        _ensure(world)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {world.digest: "e" * 64})
    assert _ensure(world)[0] == "release_qualified"


def test_entry_type_and_operation_status_are_mac_bound(world):
    """codex F067: a qualified entry's payload status is authenticated, and one entry type
    cannot stand in for another. Mutation: leaving type or status out of the MAC."""
    _ensure(world)
    store = q.Store()
    (qualified,) = store.host_dir.glob("qualified-*.json")
    raw = json.loads(qualified.read_text())
    forged = dict(raw, payload=dict(raw["payload"], operations={"completion": "passed"}))
    qualified.write_text(json.dumps(forged))
    q._HELP_MEMO.clear()
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        _admit(world)
    # the same bytes relabelled as a failed entry: its type is in the MAC context
    failed = store._path("failed", store._failed_context(world.digest, HOST, q.agy_profile_digest()))
    failed.write_text(json.dumps(dict(raw, type="failed")))
    failed.chmod(0o600)
    assert store.get_failed(world.digest, HOST, q.agy_profile_digest()) is None


def test_member_cache_is_domain_separated_by_type(world):
    """claude 5.3: the member-digest cache carries its own type tag in the MAC."""
    store = q.Store()
    store.create()
    context = {"x": 1}
    store.put("member_cache", context, context, {"member_sha256": "0" * 64})
    path = store._path("member_cache", context)
    raw = json.loads(path.read_text())
    raw["type"] = "provenance"  # relabel the file too: only the MAC's type tag separates them
    path.write_text(json.dumps(raw))
    path.rename(store._path("provenance", context))
    assert store.get("provenance", context, context) is None


def test_forged_qualified_entry_without_authenticated_provenance_executes_nothing(world):
    """codex F064 / claude 5.1 option (b):
    test_cached_qualification_requires_authenticated_provenance_before_help."""
    _ensure(world)
    store = q.Store()
    for path in store.host_dir.glob("provenance-*.json"):
        path.unlink()
    world.counter.help = 0
    q._HELP_MEMO.clear()
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        _admit(world)
    assert world.counter.help == 0


# ------------------------------------------------------------------------------ D2 key

@pytest.mark.parametrize("field", ["operations", "profile_id", "platform", "help"])
def test_record_differing_in_one_key_field_is_absent(world, monkeypatch, field):
    """D2. Mutation: dropping that field from the qualified entry's MAC context."""
    _ensure(world)
    q._HELP_MEMO.clear()
    if field == "operations":
        operation = q.OPERATIONS_CONTRACT[0]._replace(pass_predicate_id="other_predicate")
        monkeypatch.setattr(q, "OPERATIONS_CONTRACT", (operation, *q.OPERATIONS_CONTRACT[1:]))
    elif field == "profile_id":
        monkeypatch.setattr(gh, "PROFILE_ID", "agy_memfd_home_deny_all_v2")
    elif field == "platform":
        monkeypatch.setattr(prov, "detect_platform", lambda **_: prov.HostPlatform("linux", "x64", "musl"))
    elif field == "help":
        monkeypatch.setattr(q, "_run_help", lambda verified, env: b"different help\n")
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        _admit(world)


def test_record_for_image_a_under_image_b_lookup_name_is_absent(world):
    _ensure(world)
    store = q.Store()
    host, runtime = HOST, q.agy_profile_digest()
    other = sha256(b"image B").hexdigest()
    help_sha256 = sha256(b"synthetic help\n").hexdigest()
    for kind, name_a, name_b in (
        ("provenance", {**store._base(world.digest, host.name, runtime), "asset": host.asset},
         {**store._base(other, host.name, runtime), "asset": host.asset}),
        ("qualified", store._qualified_contexts(world.digest, help_sha256, host, runtime)[0],
         store._qualified_contexts(other, help_sha256, host, runtime)[0]),
    ):
        store._path(kind, name_b).write_bytes(store._path(kind, name_a).read_bytes())
        store._path(kind, name_b).chmod(0o600)
    assert store.get_provenance(other, host, runtime) is None


def test_verifier_binds_records_to_the_seat_qci_not_the_route_core():
    """RECBIND (AGYROLL §3.3): no CI gate pins route-core file hashes any more; records bind to
    ``seat_qci()``, which the watch and the verifier read from the same tree."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
    if not script.is_file():
        pytest.skip("scripts/ is repository source")  # pragma: no cover - sdist layout only
    text = script.read_text()
    assert "ROUTE_CORE" not in text and "--route-core" not in text.replace("``--route-core``", "")
    assert "seat_qci" in text
    assert {"gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py"} <= set(q.ROUTE_CORE)
    assert "agy_watch.py" not in q.ROUTE_CORE


def test_profile_digest_is_independent_of_the_reviewed_tree(world, tmp_path, monkeypatch):
    before = q.agy_profile_digest()
    fake = tmp_path / "reviewed" / "phase-loop-runtime/src/phase_loop_runtime"
    fake.mkdir(parents=True)
    for name in q.ROUTE_CORE:
        (fake / name).write_text("# reviewed tree\n")
    monkeypatch.chdir(fake)
    monkeypatch.syspath_prepend(str(fake.parent))
    assert q.agy_profile_digest() == before


# -------------------------------------------------------------- I2, negative records

def test_failed_operation_writes_a_failed_entry_that_refuses_without_launching(world):
    """I2. Mutation: letting lookup admit (or ignore) a failed entry."""
    world.outcome = {"status": "failed", "operation": "owner-loss", "reason": "operation_validation_failed"}
    with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
        _ensure(world)
    assert "failed" in _entries(world)
    world.counter.help = world.counter.qualify = 0
    q._HELP_MEMO.clear()
    for call in (lambda: _admit(world), lambda: _ensure(world)):
        with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
            call()
    assert (world.counter.help, world.counter.qualify) == (0, 0)


def test_clear_removes_the_failed_entry(world, capsys):
    world.outcome = {"status": "failed", "operation": "cancel"}
    with pytest.raises(ValueError):
        _ensure(world)
    assert q.cli_main(SimpleNamespace(action="clear", all=False)) == 0
    assert "failed" not in _entries(world)


@pytest.mark.parametrize("status", ["transient", "cancelled"])
def test_transients_and_cancellation_write_no_verdict_entry(world, status):
    world.outcome = {"status": status}
    with pytest.raises(ValueError):
        _ensure(world)
    assert "failed" not in _entries(world) and "qualified" not in _entries(world)


@pytest.mark.parametrize("failure,result,expected", [
    (None, None, "transient"),  # never started observing
    ({"stage": "admission_observation", "reason": "qualification ended before complete admission observation"},
     None, "transient"),
    ({"stage": "launch", "reason": "qualification local failure"}, None, "transient"),
    ({"stage": "validation", "reason": "gemini qualification record rejected"}, "UNAVAILABLE", "transient"),
    ({"stage": "validation", "reason": "gemini qualification record rejected"}, "OK", "failed"),
    ({"stage": "cleanup_observation", "reason": "qualification observed a surviving owned process"}, "OK", "failed"),
    # codex B1: an observed violation is terminal at ANY stage
    ({"stage": "helper_observation", "reason": "qualification helper executable is outside the registered identity policy",
      "rejected_image": {"pid": 1}}, None, "failed"),
    ({"stage": "admission_observation", "reason": "qualification observed an unqualified provider image"}, None, "failed"),
    ({"stage": "admission_observation", "reason": "qualification executable mount is not read-only"}, None, "failed"),
    ({"stage": "admission_observation", "reason": "qualification network rule observation failed"}, None, "failed"),
])
def test_failure_classification(tmp_path, failure, result, expected):
    """codex B1 on agent-harness#1130 r1. Mutation: classifying by stage alone."""
    if failure is not None:
        (tmp_path / "failure.json").write_text(json.dumps(failure))
    if result is not None:
        (tmp_path / "terminal.json").write_text(json.dumps({"result": {"status": result}}))
    assert q._classify_failure(tmp_path, "completion") == expected


def test_real_helper_policy_rejection_writes_a_terminal_failed_entry(world, monkeypatch):
    """codex B1: drive the REAL HelperObserver against a live process whose executable is
    outside the registered policy, record it with the driver's own write_failure, and let
    the real qualify_image classify it. A failed entry results and the next admission
    executes nothing. Mutation: treating helper_observation failures as transient."""
    monkeypatch.setattr(q, "qualify_image", _REAL_QUALIFY)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        def run_operation(operation, root, *a, **k):
            root.mkdir(parents=True)
            helpers = q.HelperObserver("0" * 64, {})
            start = q.gh._proc_stat(child.pid)[2]
            try:
                helpers.observe(child.pid, start)
            except q.QualificationFailure as exc:
                q.write_failure(root, exc, "helper_observation", helpers, {})
                raise
            raise AssertionError("the observer admitted an unregistered executable")

        monkeypatch.setattr(q, "run_operation", run_operation)
        with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
            _ensure(world)
    finally:
        child.kill()
        child.wait()
    assert "failed" in _entries(world)
    world.counter.help = 0
    q._HELP_MEMO.clear()
    for call in (lambda: _admit(world), lambda: _ensure(world)):
        with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
            call()
    assert world.counter.help == 0


def test_repeated_transients_become_a_failed_entry(world):
    """claude N2: a deterministic incompatibility that always looks transient stops
    re-running after MAX_TRANSIENT_ATTEMPTS. Mutation: never counting transients."""
    world.outcome = {"status": "transient", "operation": "completion"}
    for _ in range(q.MAX_TRANSIENT_ATTEMPTS - 1):
        with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_UNAVAILABLE):
            _ensure(world)
        assert "failed" not in _entries(world)
    with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
        _ensure(world)
    assert "failed" in _entries(world)
    assert world.counter.qualify == q.MAX_TRANSIENT_ATTEMPTS


@pytest.mark.parametrize("error_class", [
    "auth_missing", "auth_expired", "quota_exhausted", "permission_denied", "model_error",
    "empty_response", "network", "timeout", "unknown", "private fixture text", None,
])
def test_provider_error_class_projection_is_allowlisted(tmp_path, error_class):
    q.write_json(tmp_path / "terminal.json", {
        "result": {"status": "ERROR", "detail": "PRIVATE_FIXTURE_SENTINEL"},
        "broker": {"provider_error_class": error_class},
    })
    exc = q.QualificationFailure(q.ENDED_BEFORE_ADMISSION)
    q.write_failure(tmp_path, exc, "terminal_observation", q.HelperObserver("0" * 64, {}), {})
    failure = json.loads((tmp_path / "failure.json").read_text())
    if error_class is None or error_class == "private fixture text":
        assert "provider_error_class" not in failure
    else:
        assert failure["provider_error_class"] == error_class
    assert "PRIVATE_FIXTURE_SENTINEL" not in json.dumps(failure)


def test_provider_error_class_survives_the_first_use_refusal(world, monkeypatch):
    monkeypatch.setattr(q, "qualify_image", _REAL_QUALIFY)

    def run_operation(operation, root, *args, **kwargs):
        assert operation == "completion"
        root.mkdir()
        q.write_json(root / "terminal.json", {
            "result": {"status": "ERROR"},
            "broker": {"provider_error_class": "unknown"},
        })
        exc = q.QualificationFailure("gemini qualification record rejected")
        q.write_failure(root, exc, "validation", q.HelperObserver(world.digest, {}), {})
        raise exc

    monkeypatch.setattr(q, "run_operation", run_operation)
    with pytest.raises(ValueError, match=f"^{q.SELF_QUALIFICATION_UNAVAILABLE}$") as exc:
        _ensure(world)
    assert q.qualification_notice(exc.value) == {"code": q.SELF_QUALIFICATION_UNAVAILABLE,
                                                  "detail": {"provider_error_class": "unknown"}}
    assert "failed" not in _entries(world)


def test_provider_error_class_is_rendered_by_qualification_and_advisor_board(
    world, monkeypatch, capsys,
):
    from phase_loop_runtime import cli
    from phase_loop_runtime import seat_subject

    def refuse(*args, **kwargs):
        raise q.QualificationUnavailable(q.ProviderErrorClass.EMPTY_RESPONSE)

    monkeypatch.setattr(q, "requalify_once", refuse)
    monkeypatch.setattr(seat_subject, "resolve_seat_subject", lambda *args: SimpleNamespace(subject_path=None))
    monkeypatch.setattr(q.panel, "integrated_seat_subject", lambda *args: SimpleNamespace(subject_path=None))
    assert q.cli_main(SimpleNamespace(action="run")) == 1
    stderr = capsys.readouterr().err.splitlines()
    assert stderr[0] == f"phase-loop agy-qualification run: {q.SELF_QUALIFICATION_UNAVAILABLE}"
    notice = {"code": q.SELF_QUALIFICATION_UNAVAILABLE, "detail": {"provider_error_class": "empty_response"}}
    assert json.loads(stderr[1]) == notice

    assert cli._advisor_board_command(args=SimpleNamespace(monitoring_policy="heartbeat_only", json=True)) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["monitoring"]["diagnostic"] == q.SELF_QUALIFICATION_UNAVAILABLE
    assert payload["notice"] == notice


def test_local_path_validates_with_the_release_paths_own_validator(world, monkeypatch, tmp_path):
    """I2 validation parity. Mutation: a local-only validator that skips validate_records."""
    calls = []
    monkeypatch.undo()  # the real qualify_image, not the fake
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state2"))
    monkeypatch.setattr(q, "run_operation", lambda *a, **k: calls.append(("op", a[0])))

    def validator(root, **expected):
        calls.append(("validate", expected["expected_image_sha256"], expected["expected_help_sha256"]))
        raise q.QualificationFailure("gemini qualification record rejected")

    monkeypatch.setattr(q, "validate_directory", validator)
    store = q.Store()
    store.create()
    image = gh.VerifiedImage.from_bytes(b"img")
    try:
        outcome = q.qualify_image(image, b"help", store=store)
    finally:
        image.close()
    assert [c[0] for c in calls] == ["op", "op", "op", "validate"]
    assert calls[-1][1:] == (sha256(b"img").hexdigest(), sha256(b"help").hexdigest())
    assert outcome["status"] == "failed"


def test_qualification_sweep_failure_does_not_prevent_launch(monkeypatch, tmp_path, caplog):
    from phase_loop_runtime import seat_resource_caps as caps

    def fail_directory(**kwargs):
        with store.try_lock() as acquired:
            assert not acquired
        raise PermissionError("test owner directory failure")

    monkeypatch.setattr(caps, "_owner_directory", fail_directory)
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    seen = []
    monkeypatch.setattr(q, "run_operation", lambda *a, **k: seen.append(k["_launch_class"]))
    monkeypatch.setattr(q, "validate_directory", lambda *a, **k: {"route_qualified": True})
    store = q.Store()
    store.create()
    image = gh.VerifiedImage.from_bytes(b"stand-in")
    try:
        assert q.qualify_image(image, b"help", store=store) == {"status": "passed"}
    finally:
        image.close()
    assert seen == [caps._LaunchClass.QUALIFICATION] * len(q.OPERATIONS)
    assert "test owner directory failure" in caplog.text


# --------------------------------------------------------------------- I3 concurrency

_CHILD = textwrap.dedent('''
    import json, os, sys, time
    from hashlib import sha256
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from phase_loop_runtime import agy_qualification as q, agy_provenance as prov, gemini_heartbeat as gh
    from phase_loop_runtime import agy_attestation as att
    tmp = Path(sys.argv[2]); mode = sys.argv[3]
    q.read_machine_id = lambda path="/etc/machine-id": "a" * 32
    prov.detect_platform = lambda **_: prov.HostPlatform("linux", "x64", "glibc")
    gh.QUALIFIED_IMAGES = {"f" * 64: "e" * 64}
    class NoAttestation:
        """The autouse ``upstream_channel`` fixture does not reach a child process: as there,
        GitHub lists no attestation (404), and no other upstream request is expected, so
        nothing here reaches the network."""
        status = 404
        def open(self, url, *, accept):
            from urllib.parse import urlsplit
            parts = urlsplit(url)
            if parts.hostname == prov.API_HOST and "/attestations/" in parts.path:
                return self
            raise AssertionError(f"unexpected upstream-channel request {url}")
        def read(self, n=-1):
            return b""
        def close(self):
            pass
    att._Opener = lambda **_: NoAttestation()
    image = (tmp / "bin" / "agy").read_bytes()
    class T:
        def __init__(self):
            import io, tarfile
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as b:
                info = tarfile.TarInfo("antigravity"); info.size = len(image); b.addfile(info, io.BytesIO(image))
            self.archive = buf.getvalue()
        def open(self, url, *, accept):
            import io
            archive = self.archive
            if "api.github.com" in url:
                return io.BytesIO(json.dumps([{"tag_name": "1.2.99", "draft": False, "prerelease": False,
                    "assets": [{"name": prov.HostPlatform("linux","x64","glibc").asset,
                                "browser_download_url": prov.DOWNLOAD_PREFIX + "1.2.99/agy_cli_linux_x64.tar.gz",
                                "digest": "sha256:" + sha256(archive).hexdigest()}]}]).encode())
            return io.BytesIO(archive)
    if mode == "archive-stability":
        from unittest.mock import patch
        transport = T()
        with patch("gzip.time.time", return_value=1700000000):
            listing = json.load(transport.open("https://api.github.com/releases", accept="application/json"))
        with patch("gzip.time.time", return_value=1700000001):
            archive = transport.open("https://github.com/release.tar.gz", accept="application/octet-stream").read()
        assert listing[0]["assets"][0]["digest"] == "sha256:" + sha256(archive).hexdigest()
        print("stable_archive", flush=True)
        sys.exit(0)
    q._run_help = lambda image, env: b"help\\n"
    def qualify(image, help_bytes, **_):
        with open(tmp / "qualifications", "a") as f:
            f.write(f"{os.getpid()}\\n")
        (tmp / f"holding-{os.getpid()}").write_text("")
        if mode == "hold":
            if sys.argv[4:5] == ["spawn"]:
                import subprocess
                child = subprocess.Popen([sys.executable, "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]);"
                    "from phase_loop_runtime import agy_qualification as q; q._set_parent_death_signal();"
                    "import time; time.sleep(120)", sys.argv[1]])
                (tmp / "worker.pid").write_text(str(child.pid))
            time.sleep(120)
        time.sleep(0.5)
        return {"status": "passed"}
    q.qualify_image = qualify
    env = {"PATH": str(tmp / "bin"), "HOME": str(tmp / "home")}
    admission = q.ensure_admitted(env, transport=T())
    print(admission.admission_class, flush=True)
''')


def _child(world, mode, *extra):
    env = dict(os.environ, XDG_STATE_HOME=str(world.tmp / "state"), XDG_CONFIG_HOME=str(world.tmp / "config"))
    src = str(Path(q.__file__).resolve().parents[1])
    return subprocess.Popen([sys.executable, "-c", _CHILD, src, str(world.tmp), mode, *extra],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def _wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def test_two_racing_processes_qualify_once_and_both_are_admitted(world):
    """I3. Mutation: taking the lock without re-checking the store after acquiring it."""
    first, second = _child(world, "normal"), _child(world, "normal")
    outs = [p.communicate(timeout=60) for p in (first, second)]
    assert [o[0].strip() for o in outs] == ["locally_qualified", "locally_qualified"], outs
    assert len((world.tmp / "qualifications").read_text().split()) == 1


def test_concurrency_fixture_archive_matches_its_digest_across_clock_ticks(world):
    child = _child(world, "archive-stability")
    out, err = child.communicate(timeout=60)
    assert child.returncode == 0, err
    assert out.strip() == "stable_archive"


def test_killing_the_lock_holder_hands_off_and_leaves_no_orphan_worker(world):
    """I3 hand-off + claude 5.4 orphan falsifier: SIGKILL the holder mid-operation; its
    PDEATHSIG-bound worker is gone before the next holder's first launch."""
    holder = _child(world, "hold", "spawn")
    _wait_for(lambda: (world.tmp / "worker.pid").exists())
    worker_pid = int((world.tmp / "worker.pid").read_text())
    waiter = _child(world, "normal")
    time.sleep(0.5)
    assert waiter.poll() is None  # blocked on the lock
    holder.kill()
    holder.wait(10)
    _wait_for(lambda: _gone(worker_pid), timeout=10)
    out, err = waiter.communicate(timeout=60)
    assert out.strip() == "locally_qualified", err
    assert len((world.tmp / "qualifications").read_text().split()) == 2


def _gone(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] == "Z"
    except (FileNotFoundError, ProcessLookupError):
        return True


def test_a_waiter_is_cancellable(world):
    store = q.Store()
    store.create()
    cancel = threading.Event()
    with store.lock():
        result = {}

        def wait():
            try:
                with q.Store().lock(cancel):
                    result["acquired"] = True
            except ValueError as exc:
                result["error"] = str(exc)

        thread = threading.Thread(target=wait)
        thread.start()
        time.sleep(0.3)
        cancel.set()
        thread.join(5)
    assert result == {"error": "review_operation_cancelled"}


def test_lock_waiters_emit_heartbeats(world):
    store = q.Store()
    store.create()
    beats, cancel = [], threading.Event()
    with store.lock():
        thread = threading.Thread(target=lambda: _swallow(lambda: q.Store().lock(cancel, beats.append).__enter__()))
        thread.start()
        time.sleep(0.35)
        cancel.set()
        thread.join(5)
    assert beats and set(beats) == {"agy_qualification_lock_wait"}


def _swallow(fn):
    try:
        fn()
    except ValueError:
        pass


# -------------------------------------------------------------------------- transport

class _Recorder:
    def __init__(self, responses):
        self.responses, self.requests, self.hosts, self.contexts = list(responses), [], [], []

    def __call__(self, host, port, *, context, timeout):
        self.hosts.append((host, port))
        self.contexts.append(context)
        recorder = self

        class Conn:
            def request(self, method, target, headers):
                recorder.requests.append((method, host, target, dict(headers)))

            def getresponse(self):
                status, location, body = recorder.responses.pop(0)
                return SimpleNamespace(status=status, getheader=lambda name: location,
                                       read=io.BytesIO(body).read, close=lambda: None)

            def close(self):
                pass

        return Conn()


def test_transport_ignores_credentials_proxies_and_ca_overrides(monkeypatch, tmp_path):
    """Mutation: urllib (honours *_proxy/.netrc) or ssl.create_default_context (honours
    SSL_CERT_FILE)."""
    (tmp_path / ".netrc").write_text("machine api.github.com login x password SECRET\n")
    for key, value in {"HOME": str(tmp_path), "GITHUB_TOKEN": "SECRET", "GH_TOKEN": "SECRET",
                       "HTTPS_PROXY": "http://proxy.invalid:3128", "https_proxy": "http://proxy.invalid:3128",
                       "ALL_PROXY": "http://proxy.invalid:3128", "SSL_CERT_FILE": str(tmp_path / "bogus.pem"),
                       "SSL_CERT_DIR": str(tmp_path), "REQUESTS_CA_BUNDLE": str(tmp_path / "bogus.pem")}.items():
        monkeypatch.setenv(key, value)
    loaded = []
    real_load = prov.ssl.SSLContext.load_verify_locations
    monkeypatch.setattr(prov.ssl.SSLContext, "load_verify_locations",
                        lambda self, cafile=None, capath=None, cadata=None: loaded.append((cafile, capath))
                        or real_load(self, cafile=cafile, capath=capath))
    recorder = _Recorder([(200, None, b"[]")])
    prov.stable_releases(prov._Transport(connection=recorder))
    assert recorder.hosts == [(prov.API_HOST, 443)]
    ((_, host, _, headers),) = recorder.requests
    assert "Authorization" not in headers and "SECRET" not in json.dumps(headers)
    assert loaded and all(str(tmp_path) not in str(pair) for pair in loaded)
    paths = prov.ssl.get_default_verify_paths()
    assert loaded[0] in {(c if c and os.path.isfile(c) else None, p if p and os.path.isdir(p) else None)
                         for c, p in [(paths.openssl_cafile, paths.openssl_capath)]}


def test_redirects_are_https_only_allowlisted_and_bounded(monkeypatch):
    """claude 5.7. Mutation: following any Location, or an unbounded chain."""
    ok = _Recorder([(302, "https://release-assets.githubusercontent.com/x?sig=1", b""), (200, None, b"data")])
    response = prov._Transport(connection=ok, context_factory=lambda: None).open(
        f"{prov.DOWNLOAD_PREFIX}1.2.99/{HOST.asset}", accept="*/*")
    assert response.read() == b"data"
    assert [h for h, _ in ok.hosts] == ["github.com", "release-assets.githubusercontent.com"]
    for location in ("http://release-assets.githubusercontent.com/x", "https://evil.example/x",
                     "https://user:pw@github.com/x", "https://github.com:8443/x"):
        bad = _Recorder([(302, location, b""), (200, None, b"data")])
        with pytest.raises(prov.ProvenanceError):
            prov._Transport(connection=bad, context_factory=lambda: None).open(
                f"{prov.DOWNLOAD_PREFIX}1.2.99/{HOST.asset}", accept="*/*")
    loop = _Recorder([(302, "https://github.com/again", b"")] * (prov.MAX_REDIRECTS + 2))
    with pytest.raises(prov.ProvenanceError):
        prov._Transport(connection=loop, context_factory=lambda: None).open("https://github.com/start", accept="*/*")


# ---------------------------------------------------------------------------- D3 opt-out

def _golden_require_capability(env, qualified):
    """require_capability at the merge base (b687e311, after agent-harness#1119), verbatim
    but for its constants passed as a parameter."""
    import shutil as _shutil
    from phase_loop_runtime.agy_canary_evidence import (AgyCanaryEvidenceError, _linux_memfd_seal_abi,
                                                        _sealed_tree_fd)

    def _read_image(path):
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(gh._CAPABILITY)
            chunks = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            data = b"".join(chunks)
            if sha256(data).hexdigest() not in qualified:
                raise ValueError(gh._CAPABILITY)
            return data
        finally:
            os.close(fd)

    try:
        _linux_memfd_seal_abi()
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ValueError(gh._CAPABILITY)
        image = _shutil.which("agy", path=env.get("PATH", os.defpath))
        if image is None:
            raise ValueError(gh._CAPABILITY)
        _read_image(image)
        fd = _sealed_tree_fd(data=b"", executable=False, label="agy-capability")
        os.close(fd)
        fd = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(fd, 0)
        finally:
            os.close(fd)
        return Path(image)
    except (OSError, AgyCanaryEvidenceError, ValueError) as exc:
        raise ValueError(gh._CAPABILITY) from exc


def _outcome(fn):
    try:
        return ("ok", str(fn()))
    except ValueError as exc:
        return ("refused", str(exc))


def _opt_out(world):
    config = world.tmp / "config" / "agent-harness" / "advisor-boards.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[agy]\nself_qualification = false\n")


@pytest.mark.parametrize("image", ["release", "non_release", "missing", "symlinked_release", "symlinked_non_release"])
def test_opt_out_is_exactly_todays_require_capability(world, monkeypatch, image):
    """D3 golden parity, with a VALID local record seeded, across the preflight, per-leg
    and president paths: same result, same diagnostic, zero store reads, zero network,
    zero executions. Mutation: consulting the store before the opt-out."""
    _ensure(world)  # seed a valid local record for the non-release image
    world.transport.calls.clear()
    _opt_out(world)
    q._HELP_MEMO.clear()
    world.counter.help = world.counter.qualify = 0
    qualified = {"f" * 64: "e" * 64}
    if image in ("release", "symlinked_release"):
        qualified = {world.digest: "e" * 64}
    if image.startswith("symlinked"):
        target = world.tmp / "versions" / "agy-real"
        target.parent.mkdir()
        target.write_bytes(world.image)
        target.chmod(0o755)
        world.agy.unlink()
        world.agy.symlink_to(target)
    if image == "missing":
        world.agy.unlink()
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", qualified)
    reads = []
    monkeypatch.setattr(q.Store, "get", lambda self, *a, **k: reads.append(a) or None)
    world.transport.fail = AssertionError("network")
    golden = _outcome(lambda: _golden_require_capability(world.env, qualified))
    panel = q._panel()
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    monkeypatch.setattr(panel, "_broker_subscription_env", lambda env=None: dict(world.env))
    def leg_profile():
        # the per-leg owned profile with no admission passed: it admits by lookup itself
        with gh.owned_profile(world.env, settings_bytes=b"{}\n", credential_path=world.token):
            return golden[1]

    def president():
        from phase_loop_runtime import president_adapter
        try:
            president_adapter.PresidentInvoke._launch_gemini(
                SimpleNamespace(base_env=world.env), "gemini-3.8-flash-high", "prompt", world.tmp, monitor=object())
        except ValueError:
            raise
        except Exception:  # noqa: BLE001 - admitted; the fake monitor stops the launch after admission
            return golden[1]

    paths = {
        "per_leg": lambda: gh.require_capability(world.env),
        "leg_profile": leg_profile,
        "president": president,
        "preflight": lambda: panel._preflight_gemini_heartbeat(DEFAULT_BOARD, "heartbeat_only") or golden[1],
    }
    for name, call in paths.items():
        outcome = _outcome(call)
        if golden[0] == "ok" and name != "per_leg":
            assert outcome == ("ok", golden[1]), name
        else:
            assert outcome == golden, name
    assert reads == [] and world.transport.calls == []
    assert (world.counter.help, world.counter.qualify) == (0, 0)


@pytest.mark.parametrize("text,enabled", [
    ("", True), ("[agy]\nself_qualification = true\n", True), ("[agy]\nself_qualification = false\n", False),
    ('[agy]\nself_qualification = "false"\n', False), ("[agy]\nunknown = 1\n", False), ("not toml [", False),
])
def test_user_config_opt_out_fails_closed(world, text, enabled):
    config = world.tmp / "config" / "agent-harness" / "advisor-boards.toml"
    config.parent.mkdir(parents=True)
    config.write_text(text)
    assert q.self_qualification_enabled() is enabled


def test_repository_config_still_rejects_an_agy_table(tmp_path):
    from phase_loop_runtime.advisor_board import config as cfg
    repo = tmp_path / "repo" / ".agent-harness"
    repo.mkdir(parents=True)
    (repo / "advisor-boards.toml").write_text("[agy]\nself_qualification = true\n")
    with pytest.raises(cfg.BoardConfigError, match="agy"):
        cfg.load_president_ladder(tmp_path / "repo", env={})


# ----------------------------------------------------------------------------------- D4

def test_platform_detection_reads_the_running_host_not_config_or_environment(monkeypatch):
    monkeypatch.setenv("AGY_PLATFORM", "linux-arm64-musl")
    uname = lambda: SimpleNamespace(sysname="Linux", machine="x86_64")  # noqa: E731
    fresh = prov
    host = fresh.detect_platform(uname=uname, libc_ver=lambda exe: ("glibc", "2.35"), musl_loaders=lambda: [])
    assert (host.name, host.asset) == ("linux-x64", "agy_cli_linux_x64.tar.gz")
    musl = fresh.detect_platform(uname=lambda: SimpleNamespace(sysname="Linux", machine="aarch64"),
                                 libc_ver=lambda exe: ("", ""), musl_loaders=lambda: ["/lib/ld-musl-aarch64.so.1"])
    assert (musl.name, musl.asset) == ("linux-arm64-musl", "agy_cli_linux_arm64_musl.tar.gz")
    for uname_value, libc in ((SimpleNamespace(sysname="Darwin", machine="arm64"), ("", "")),
                              (SimpleNamespace(sysname="Linux", machine="riscv64"), ("glibc", "2.39")),
                              (SimpleNamespace(sysname="Linux", machine="x86_64"), ("", ""))):
        with pytest.raises(fresh.ProvenanceError, match=fresh.UNSUPPORTED):
            fresh.detect_platform(uname=lambda v=uname_value: v, libc_ver=lambda exe, l=libc: l, musl_loaders=lambda: [])


def test_unsupported_platform_refuses_before_any_network_call(world, monkeypatch):
    def unsupported(**_):
        raise prov.ProvenanceError(prov.UNSUPPORTED)

    monkeypatch.setattr(prov, "detect_platform", unsupported)
    with pytest.raises(ValueError, match=prov.UNSUPPORTED):
        _ensure(world)
    assert world.transport.calls == []


# ----------------------------------------------------------------------------------- D1

def _leg(text="Looks fine.\nAGREE", *, leg="gemini", admission_class=None, digest="d" * 64,
         policy="heartbeat_only", status="OK"):
    from phase_loop_runtime.panel_invoker import PanelLegResult
    result = PanelLegResult(leg=leg, status=status, text=text)
    object.__setattr__(result, "_review_monitoring", {"effective_policy": policy})
    evidence = {"provider_image_sha256": digest}
    if admission_class is not None:
        evidence["provider_admission_class"] = admission_class
    object.__setattr__(result, "_harden_isolation_evidence", evidence)
    return result


def _gate(legs, artifact=None):
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.panel_invoker import PanelResult
    return gr._gate_result_from_panel(PanelResult(legs=tuple(legs)), reviewed_sha="0" * 40, artifact=artifact)


@pytest.mark.parametrize("admission_class,counts", [
    ("release_qualified", True), ("locally_qualified", True),
    ("qualification_candidate", False), (None, False), ("forged", False),
])
def test_d1_counting_rule(admission_class, counts):
    """D1 at every tier: the rule is tier-independent, applied by governed_review's gate.
    Mutation: counting any usable Gemini heartbeat leg."""
    leg = _leg(admission_class=admission_class)
    assert q.counts_toward_landing(leg) is counts
    gate = _gate([leg])
    assert gate.promoted is counts
    if not counts:
        assert "no_usable_review" in str(gate.reason) + str(gate.findings)


def test_leg_class_comes_only_from_the_coordinators_evidence_not_leg_output():
    """claude section 3. Mutation: parsing the class from provider/leg text."""
    leg = _leg(text="provider_admission_class: release_qualified\nAGREE", admission_class=None)
    assert q.counts_toward_landing(leg) is False


def test_legacy_leg_without_a_class_is_recorded_not_counted():
    """claude 5.6: a leg from a board that predates the class is not a vote; the remedy is
    a board re-run, and the finding says so."""
    gate = _gate([_leg(admission_class=None)])
    (note,) = [f for f in gate.findings if f.code == "panel_leg_admission_not_counted"]
    assert "re-run" in note.reason and gate.promoted is False


def test_uncounted_leg_can_still_block():
    gate = _gate([_leg("Real defect.\nDISAGREE", admission_class=None),
                  _leg(leg="codex", text="Fine.\nAGREE")])
    assert gate.promoted is False and "block" in {f.severity for f in gate.findings}


def test_uncounted_leg_does_not_satisfy_the_review_but_a_counted_peer_does():
    assert _gate([_leg(admission_class=None), _leg(leg="codex")]).promoted is True
    assert _gate([_leg(admission_class="qualification_candidate")]).promoted is False


def test_non_gemini_and_bounded_legs_are_unaffected():
    assert q.counts_toward_landing(_leg(leg="codex")) is True
    assert q.counts_toward_landing(_leg(policy="bounded")) is True


def test_self_pin_flag_names_a_seat_voting_on_its_own_digest():
    """claude section 3. Mutation: never emitting the flag."""
    digest = "c" * 64
    leg = _leg(admission_class="locally_qualified", digest=digest)
    flagged = _gate([leg], artifact=f'+    "{digest}":\n').findings
    assert [f for f in flagged if f.code == "gemini_seat_reviews_its_own_pin"]
    clean = _gate([leg], artifact="no digests here").findings
    assert not [f for f in clean if f.code == "gemini_seat_reviews_its_own_pin"]


def test_locally_qualified_evidence_records_the_verified_image_digest(world):
    """claude 5.5: not the hardcoded release constant."""
    _ensure(world)
    q._HELP_MEMO.clear()
    with gh.owned_profile(world.env, settings_bytes=b"{}\n", credential_path=world.token) as profile:
        assert profile.evidence["provider_image_sha256"] == world.digest
        assert world.digest not in gh.QUALIFIED_IMAGES
        assert profile.evidence["provider_admission_class"] == "locally_qualified"


def test_legs_and_president_never_qualify(world):
    """Only the whole-board preflight qualifies. Mutation: require_capability/owned_profile
    falling through to ensure_admitted."""
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        gh.require_capability(world.env)
    with pytest.raises(ValueError):
        with gh.owned_profile(world.env, settings_bytes=b"{}\n", credential_path=world.token):
            pass
    assert (world.counter.help, world.counter.qualify) == (0, 0) and world.transport.calls == []
    assert q.Store().status() == "absent"


# -------------------------------------------------------------------------------- watch

def _watch_repo(tmp_path):
    """A minimal prepared-tree layout copied from this checkout."""
    root = Path(__file__).resolve().parents[2]
    from phase_loop_runtime import agy_watch
    if not (root / agy_watch.CATALOG).is_file():
        # A repository checkout always ships the data catalog: missing it there is a failure,
        # never a skip (RECBIND). Only a layout without the repository may skip.
        if (root / ".git").exists():
            pytest.fail(f"the agy data catalog {agy_watch.CATALOG} is missing from this checkout")
        pytest.skip("repository layout absent")  # pragma: no cover - sdist layout only
    tree = tmp_path / "tree"
    for rel in ("phase-loop-runtime/src/phase_loop_runtime", "phase-loop-runtime/scripts", "plans/evidence"):
        src = root / rel
        if not src.is_dir():
            pytest.skip("repository layout absent")  # pragma: no cover - sdist layout only
        import shutil
        shutil.copytree(src, tree / rel, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def agy_watch_identity_program():
    from phase_loop_runtime import agy_watch
    return agy_watch._IDENTITY_PROGRAM


def _current_base():
    """``main``'s watch label value: the seat QCI of the tree under test (AGYROLL §2.1)."""
    return q.seat_qci()


def test_watch_record_passes_contract_on_its_prepared_tree(tmp_path):
    """The watch's tree edit adds the new member to the TREE's data catalog -- and edits
    nothing else (so the tree's own worker gate admits it, claude 5.2) -- and the summarized
    v2 record passes ``verify_qualified_agy_image.py --contract`` against that tree."""
    from phase_loop_runtime import agy_watch
    tree = _watch_repo(tmp_path)

    def snapshot():
        return {path.relative_to(tree): sha256(path.read_bytes()).hexdigest()
                for path in tree.rglob("*") if path.is_file()}

    before = snapshot()
    image, help_sha = sha256(b"watch image").hexdigest(), sha256(b"watch help").hexdigest()
    member = {"version": "9.9.9", "image_sha256": image, "asset_sha256": "1" * 64, "qci": _current_base(),
              "published_at": "2026-11-07T08:38:26Z"}
    agy_watch.edit_catalog(tree, help_sha256="0" * 64, **member)
    agy_watch.edit_catalog(tree, help_sha256=help_sha, **member)  # idempotent re-edit
    after = snapshot()
    assert {name for name in set(before) | set(after) if before.get(name) != after.get(name)} == {
        Path(agy_watch.CATALOG)}
    members = agy_watch._catalog_members(tree)
    assert [m["help_sha256"] for m in members if m["image_sha256"] == image] == [help_sha]
    assert gh.load_catalog(tree / agy_watch.CATALOG)[image] == help_sha
    # receipts shaped like the newest committed record
    template = json.loads((tree / "plans/evidence" / members[-2]["record"]).read_text())
    series = tmp_path / "series"
    for row in template["records"]:
        receipt = json.loads(json.dumps(row))
        receipt.update(image_sha256=image, help_sha256=help_sha, source_sha256={"x.py": "0" * 64},
                       request=row["request_digests"])
        receipt["profile"] = dict(row["profile"], image_sha256=image)
        (series / row["operation"]).mkdir(parents=True)
        (series / row["operation"] / "qualification.json").write_text(json.dumps(receipt))
    asset = prov.ReleaseAsset("9.9.9", HOST.asset, "u", "1" * 64)
    record = agy_watch.summarize(tree, series, asset, image, help_sha, qci=_current_base(), qualified_under="9.0.0")
    assert record["schema"] == agy_watch.RECORD_SCHEMA and "source_sha256" not in record
    assert record["signatures"] == [] and record["qci"] == _current_base()
    (tree / "plans/evidence/agy-9.9.9-linux-x64-qualification.json").write_text(json.dumps(record, indent=2))
    verifier = tree / "phase-loop-runtime/scripts/verify_qualified_agy_image.py"
    result = subprocess.run([sys.executable, str(verifier), "--contract"], cwd=tree, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "9.9.9" in json.loads(result.stdout)["qualified_releases"]


class _TagTransport(FakeTransport):
    def open(self, url, *, accept):
        if "/releases/tags/" in url:
            self.calls.append(url)
            tag = url.rsplit("/", 1)[1]
            return io.BytesIO(json.dumps(next(r for r in self.releases if r["tag_name"] == tag)).encode())
        return super().open(url, accept=accept)


@pytest.mark.parametrize("flag", ["prerelease", "draft"])
def test_release_by_tag_refuses_non_stable(flag):
    t = _TagTransport()
    t.add("1.2.99", b"x", **{flag: True})
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        prov.release_by_tag(t, "1.2.99")


def test_watch_refetched_member_must_match_its_record(tmp_path):
    """The watch requalifies every catalog member on the prepared tree; an existing member's
    re-fetched image must equal its committed record. Mutation: trusting the upstream bytes."""
    from phase_loop_runtime import agy_watch
    tree = _watch_repo(tmp_path)
    member = agy_watch._catalog_members(tree)[-1]
    t = _TagTransport()
    t.add(member["release_version"], b"not the pinned image")
    with pytest.raises(prov.ProvenanceError):
        agy_watch._pinned_member(tree, member, HOST, t)


def test_watch_base_ref_is_dry_run_only(tmp_path):
    from phase_loop_runtime import agy_watch
    with pytest.raises(ValueError, match="dry-run"):
        agy_watch.main(repo=tmp_path, runner=lambda *a, **k: None, host=HOST, base_ref="HEAD")


# --------------------------------------------- PROVFWD: the unwindowed listing and two statuses

def test_summarize_writes_both_statuses_and_a_requalified_member_keeps_its_committed_second_channel(tmp_path):
    from phase_loop_runtime import agy_watch
    tree = _watch_repo(tmp_path)
    existing = agy_watch._catalog_members(tree)[-1]
    template = json.loads((tree / "plans/evidence" / existing["record"]).read_text())
    image, help_sha = existing["image_sha256"], existing["help_sha256"]
    series = tmp_path / "series"
    for row in template["records"]:
        receipt = json.loads(json.dumps(row))
        receipt.update(image_sha256=image, help_sha256=help_sha, source_sha256={"x.py": "0" * 64},
                       request=row["request_digests"])
        receipt["profile"] = dict(row["profile"], image_sha256=image)
        (series / row["operation"]).mkdir(parents=True)
        (series / row["operation"] / "qualification.json").write_text(json.dumps(receipt))
    new = agy_watch.summarize(tree, series, prov.ReleaseAsset("9.9.9", HOST.asset, "u", "1" * 64), image, help_sha,
                              qci=_current_base(), qualified_under="9.0.0", attestation="absent", second_channel="match")
    assert (new["upstream"]["attestation"], new["upstream"]["second_channel"]) == ("absent", "match")
    again = agy_watch.summarize(tree, series, prov.ReleaseAsset(existing["release_version"], HOST.asset, "u",
                                                                existing["asset_sha256"]),
                                image, help_sha, qci=_current_base(), qualified_under="9.0.0",
                                template_name=existing["record"], attestation="present_unverified",
                                second_channel=None)
    assert again["upstream"]["attestation"] == "present_unverified"
    assert again["upstream"]["second_channel"] == template["upstream"]["second_channel"]
    with pytest.raises(ValueError, match="second channel"):
        agy_watch.summarize(tree, series, prov.ReleaseAsset("9.9.9", HOST.asset, "u", "1" * 64), image, help_sha,
                            qci=_current_base(), qualified_under="9.0.0", second_channel=None)


# ------------------------------------------------------------ round-1 (agent-harness#1130)

def _fd_count():
    return len(os.listdir("/proc/self/fd"))


def test_lookup_only_misses_close_their_image_memfds(world):
    """codex B2 / claude N1. Mutation: not closing the miss's image in admit."""
    for _ in range(3):  # warm any lazily opened descriptors
        with pytest.raises(ValueError):
            gh.require_capability(world.env)
    before = _fd_count()
    for _ in range(25):
        with pytest.raises(ValueError, match=gh._CAPABILITY):
            gh.require_capability(world.env)
        with pytest.raises(ValueError, match=gh._CAPABILITY):
            with gh.owned_profile(world.env, settings_bytes=b"{}\n", credential_path=world.token):
                pass
    assert _fd_count() == before


def test_first_use_admission_and_refusals_do_not_leak_memfds(world):
    _ensure(world)
    before = _fd_count()
    for _ in range(10):
        _ensure(world)
    # The refusals below are the subject's: with the hold on, the image admitted above (now
    # kept by the HOLD cache) would be held instead (tests/test_agy_hold_cache.py).
    config = world.tmp / "config" / "agent-harness" / "advisor-boards.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[agy]\nhold = false\n")
    world.agy.write_bytes(b"#!/bin/sh\necho tampered\n")
    for _ in range(10):
        with pytest.raises(ValueError):
            _ensure(world)
    assert _fd_count() == before


def _president_seat_leg(leg_name, text, admission_class, *, policy="heartbeat_only"):
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    seat = next(s for s in DEFAULT_BOARD.seats if s.harness == leg_name)
    leg = _leg(text, leg=leg_name, admission_class=admission_class, policy=policy)
    return seat, leg


@pytest.mark.parametrize("admission_class", [None, "qualification_candidate"])
def test_president_input_builder_withholds_an_uncounted_approval_but_keeps_its_objection(admission_class, monkeypatch):
    """codex B3, settled by EXECUTION against the real ``president_findings_from_legs``.
    Before this change the builder rendered an uncounted approving leg's review as its
    seat's findings (run with ``president_input_items`` disabled below). Now it renders a
    ``not counted`` item instead, while an uncounted DISAGREE keeps its objections.
    Mutation: dropping the builder's call into agy_qualification."""
    from phase_loop_runtime import panel_invoker as panel
    approve = _president_seat_leg("gemini", "The design is sound.\n\nAGREE", admission_class)
    block = _president_seat_leg("gemini", "Real defect: the lock is never released.\n\nDISAGREE", admission_class)
    counted = _president_seat_leg("gemini", "The design is sound.\n\nAGREE", "locally_qualified")
    render = lambda pair: panel.president_findings_from_legs((pair[0],), (pair[1],))  # noqa: E731
    assert render(approve) == (f"F001: [{approve[1].seat_key}] not counted (admission {admission_class or 'missing'})",)
    assert render(block) == (f"F001: [{block[1].seat_key}] Real defect: the lock is never released.",)
    assert render(counted) == (f"F001: [{counted[1].seat_key}] The design is sound.",)
    # the pre-change behaviour, reproduced: the uncounted approval reaches the president
    monkeypatch.setattr(q, "president_input_items", lambda leg: None)
    assert render(approve) == (f"F001: [{approve[1].seat_key}] The design is sound.",)


def test_president_builder_leaves_non_gemini_and_bounded_legs_alone():
    from phase_loop_runtime import panel_invoker as panel
    for pair in (_president_seat_leg("codex", "Fine.\n\nAGREE", None),
                 _president_seat_leg("gemini", "Fine.\n\nAGREE", None, policy="bounded")):
        assert panel.president_findings_from_legs((pair[0],), (pair[1],)) == (f"F001: [{pair[1].seat_key}] Fine.",)


def test_board_preflight_emits_lock_wait_heartbeats_and_stays_cancellable(world, monkeypatch, tmp_path, capsys):
    """codex B4: contention driven through the REAL board preflight call site.
    Mutation: _preflight_gemini_heartbeat not passing a heartbeat."""
    from phase_loop_runtime import panel_invoker as panel
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    monkeypatch.setattr(panel, "_broker_subscription_env", lambda env=None: dict(world.env))
    real_find = prov.find_provenance
    monkeypatch.setattr(prov, "find_provenance", lambda *a, **k: real_find(*a, **dict(k, transport=world.transport)))
    store = q.Store()
    store.create()
    cancel, result = threading.Event(), {}
    stream = tmp_path / "stream"

    def preflight():
        try:
            panel._preflight_gemini_heartbeat(DEFAULT_BOARD, "heartbeat_only", None, cancel, stream)
        except ValueError as exc:
            result["error"] = str(exc)

    with store.lock():
        thread = threading.Thread(target=preflight)
        thread.start()
        _wait_for(lambda: (stream / "agy-qualification.json").exists(), timeout=10)
        cancel.set()
        thread.join(10)
    progress = json.loads((stream / "agy-qualification.json").read_text())
    assert progress["phase"] == "agy_qualification_lock_wait"
    assert result == {"error": "review_operation_cancelled"}
    assert "agy-qualification: agy_qualification_lock_wait" in capsys.readouterr().err


def test_board_heartbeat_is_throttled_per_phase(tmp_path, capsys):
    now = [0.0]
    beat = q.board_heartbeat(tmp_path, every_s=5, clock=lambda: now[0])
    for t in (0, 1, 2, 6):
        now[0] = t
        beat("agy_qualification_lock_wait")
    beat("agy_qualification_help")
    assert capsys.readouterr().err.count("lock_wait") == 2


def test_top_level_dry_run_makes_the_watch_a_dry_run(monkeypatch):
    """claude N7. Mutation: the subparser default overriding the parent's --dry-run."""
    from phase_loop_runtime import agy_watch, cli
    seen = {}
    monkeypatch.setattr(agy_watch, "main", lambda **kw: seen.update(kw) or 0)
    assert cli.main(["--dry-run", "agy-qualification", "watch"]) == 0
    assert seen["dry_run"] is True
    assert cli.main(["agy-qualification", "watch"]) == 0
    assert seen["dry_run"] is False


# --- smaller round-1 items

def test_one_malformed_asset_does_not_hide_older_in_window_releases(world):
    """claude N5. Mutation: aborting the search on the first unverifiable asset."""
    t = FakeTransport()
    t.add("1.2.98", world.image)
    t.add("1.2.99", world.image, archive=b"not a tarball")
    assert _ensure(world, transport=t)[0] == "locally_qualified"


def test_a_differently_named_agy_leg_is_still_classified(monkeypatch):
    """claude N6: identify an agy leg by the coordinator's profile evidence, not its name."""
    leg = _leg(leg="antigravity", admission_class=None)
    object.__setattr__(leg, "_harden_isolation_evidence", {"provider_isolation_profile": gh.PROFILE_ID})
    assert q.counts_toward_landing(leg) is False


@pytest.mark.parametrize("field", ["profile_digest", "operations", "profile_id", "platform"])
def test_qualified_mac_alone_binds_each_key_field(world, monkeypatch, field):
    """claude r1 (D2 weak mapping): a genuine qualified entry written under a key differing
    only in ``field``, then moved to the LIVE key's filename (valid provenance present), is
    absent. Mutation: dropping that field from the qualified MAC context."""
    _ensure(world)
    store, runtime, host = q.Store(), q.agy_profile_digest(), HOST
    help_sha = sha256(b"synthetic help\n").hexdigest()
    live_path = store._path("qualified", store._qualified_contexts(world.digest, help_sha, host, runtime)[0])
    other_runtime, other_host = runtime, host
    if field == "profile_digest":
        other_runtime = "0" * 64
    elif field == "platform":
        other_host = prov.HostPlatform("linux", "x64", "musl")
    with monkeypatch.context() as scoped:
        if field == "profile_id":
            scoped.setattr(gh, "PROFILE_ID", "other_profile")
            other_runtime = q.agy_profile_digest()
        elif field == "operations":
            operation = q.OPERATIONS_CONTRACT[0]._replace(pass_predicate_id="other_predicate")
            scoped.setattr(q, "OPERATIONS_CONTRACT", (operation, *q.OPERATIONS_CONTRACT[1:]))
            other_runtime = q.agy_profile_digest()
        store.put_qualified(world.digest, help_sha, other_host, other_runtime, "1.2.99")
        other_path = store._path("qualified",
                                 store._qualified_contexts(world.digest, help_sha, other_host, other_runtime)[0])
    other_path.replace(live_path)
    assert store.get_provenance(world.digest, host, runtime) is not None
    assert store.get_qualified(world.digest, help_sha, host, runtime) is None


def test_caller_keys_cannot_override_the_mac_base_context(world):
    store = q.Store()
    context = store._context("provenance", {"type": "qualified", "euid": -1, "machine_id": "x"})
    assert (context["type"], context["euid"], context["machine_id"]) == ("provenance", os.geteuid(), MACHINE)


def test_production_worker_binds_its_parent_death_signal_first(world, monkeypatch):
    """codex r1 (5.4 mapping): the REAL worker entry sets PDEATHSIG before it inspects the
    fd. Mutation: removing that call from worker()."""
    monkeypatch.chdir(world.tmp)
    order = []
    monkeypatch.setattr(q, "_set_parent_death_signal", lambda: order.append("pdeathsig"))
    monkeypatch.setattr(q, "verified_fd_image", lambda fd: order.append("fd") or (_ for _ in ()).throw(
        q.QualificationFailure("stop")))
    with pytest.raises(q.QualificationFailure):
        q.worker(world.tmp, 99, None)
    assert order == ["pdeathsig", "fd"]


def test_the_real_president_entry_never_qualifies(world, monkeypatch, tmp_path):
    """claude r1: drive president_adapter's real Gemini launch (heartbeat route) with a
    non-release image and no record: it refuses by lookup and qualifies nothing."""
    from phase_loop_runtime import president_adapter
    from phase_loop_runtime import panel_invoker as panel
    monkeypatch.setattr(panel, "_broker_subscription_env", lambda env=None: dict(world.env))
    fake_self = SimpleNamespace(base_env=world.env)
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        president_adapter.PresidentInvoke._launch_gemini(fake_self, "gemini-3.8-flash-high", "prompt", tmp_path,
                                                         monitor=object())
    assert (world.counter.help, world.counter.qualify) == (0, 0) and world.transport.calls == []
    assert q.Store().status() == "absent"


# ------------------------------------------------------------ round-2 (agent-harness#1130)

def test_transient_count_resets_on_success(world):
    """claude N1: the counter is consecutive. Mutation: never resetting it on success."""
    world.outcome = {"status": "transient", "operation": "completion"}
    for _ in range(q.MAX_TRANSIENT_ATTEMPTS - 1):
        with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_UNAVAILABLE):
            _ensure(world)
    world.outcome = {"status": "passed"}
    assert _ensure(world)[0] == "locally_qualified"
    assert "transient" not in _entries(world)


def test_clear_removes_the_transient_counter(world, capsys):
    world.outcome = {"status": "transient", "operation": "completion"}
    with pytest.raises(ValueError):
        _ensure(world)
    assert "transient" in _entries(world)
    assert q.cli_main(SimpleNamespace(action="clear", all=False)) == 0
    assert "transient" not in _entries(world)


def test_a_lock_waiter_after_a_transient_refuses_without_running_or_counting(world):
    """claude N1: N boards queued on the lock during a provider outage cost ONE attempt.
    Mutation: waiters re-running qualification after a transient seen while waiting."""
    store = q.Store()
    store.create()
    world.outcome = {"status": "transient", "operation": "completion"}
    result = {}

    waiting = threading.Event()

    def waiter():
        try:
            _ensure(world, heartbeat=lambda phase: phase == "agy_qualification_lock_wait" and waiting.set())
        except ValueError as exc:
            result["error"] = str(exc)

    with store.lock():
        thread = threading.Thread(target=waiter)
        thread.start()
        assert waiting.wait(10)  # the waiter is now blocked on the lock
        # the holder's attempt ends in a transient while the waiter waits
        store.note_transient(world.digest, HOST, q.agy_profile_digest())
    thread.join(10)
    assert result == {"error": q.SELF_QUALIFICATION_UNAVAILABLE}
    assert world.counter.qualify == 0 and world.counter.help == 0
    context = store._failed_context(world.digest, HOST, q.agy_profile_digest())
    assert store.get("transient", context, context)["count"] == 1


@pytest.mark.parametrize("exc,expected", [
    (OSError("disk"), "transient"),                                        # our own local failure
    ("ended_before_admission", "transient"),                              # provider never observed
    ("unqualified_image", "failed"),
])
def test_real_driver_write_failure_is_classified(tmp_path, exc, expected):
    """claude N2: the classifier and the driver share reason constants; exercised through
    the driver's real write_failure. Mutation: a drifted literal in _TRANSIENT_REASONS."""
    if exc == "ended_before_admission":
        exc = q.QualificationFailure(q.ENDED_BEFORE_ADMISSION)
    elif exc == "unqualified_image":
        exc = q.QualificationFailure("qualification observed an unqualified provider image")
    tmp_path.mkdir(exist_ok=True)
    q.write_failure(tmp_path, exc, "admission_observation", q.HelperObserver("0" * 64, {}), {})
    assert q._classify_failure(tmp_path, "completion") == expected
    assert q.ENDED_BEFORE_ADMISSION in q._TRANSIENT_REASONS and q.LOCAL_FAILURE in q._TRANSIENT_REASONS


def _no_fd_growth(fn, n=10):
    fn()  # warm
    before = _fd_count()
    for _ in range(n):
        fn()
    assert _fd_count() == before


def _refused(fn):
    def call():
        with pytest.raises(ValueError):
            fn()
    return call


def test_no_memfd_leak_on_the_failed_entry_exit(world):
    """claude N3. Mutation: lookup not closing its image on a raise."""
    world.outcome = {"status": "failed", "operation": "cancel"}
    with pytest.raises(ValueError):
        _ensure(world)
    _no_fd_growth(_refused(lambda: gh.require_capability(world.env)))
    _no_fd_growth(_refused(lambda: _ensure(world)))


def test_no_memfd_leak_on_the_opt_out_exit(world):
    _opt_out(world)
    _no_fd_growth(_refused(lambda: gh.require_capability(world.env)))
    _no_fd_growth(_refused(lambda: _ensure(world)))


def test_no_memfd_leak_on_the_store_unsafe_exit(world):
    q.Store().create()
    q.Store().host_dir.chmod(0o755)
    _no_fd_growth(_refused(lambda: _ensure(world)))


def test_no_memfd_leak_when_help_spawn_raises(world, monkeypatch):
    _ensure(world)
    q._HELP_MEMO.clear()

    def boom(verified, env):
        raise OSError("spawn failed")

    monkeypatch.setattr(q, "_run_help", boom)
    _no_fd_growth(_refused(lambda: gh.require_capability(world.env)))


def _resume_round_trip(tmp_path, gemini_leg):
    from phase_loop_runtime import panel_invoker as panel
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from phase_loop_runtime.president_adapter import seat_for_rung
    from phase_loop_runtime.president_operation import brief_digest, findings_digest
    board = DEFAULT_BOARD
    legs = []
    for seat in board.seats:
        if seat.harness == "gemini":
            leg = gemini_leg
            object.__setattr__(leg, "seat_key", seat.seat_key)
        else:
            leg = panel.PanelLegResult(leg=seat.harness, status="OK", text="Fine.\n\nAGREE", seat_key=seat.seat_key)
        legs.append(leg)
    findings = panel.president_findings_from_legs(board.seats, legs)
    rung = next(r for r in panel.PRESIDENT_LADDER
                if (seat := seat_for_rung(board, r)) is not None and str(seat.harness).lower() == "claude")
    deferred = panel.PresidentNativeFillDeferred(rung, {
        "brief_digest": brief_digest(panel._president_prompt(findings)),
        "findings_digest": findings_digest(findings)})
    stream = tmp_path / "stream"
    pending = panel._resolve_native_president(board, legs, findings, deferred, stream_dir=stream, fill=None, binding={})
    request = pending.needs_native_president
    text = "\n".join(f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled" for f in findings) + "\nFORCING DECISION: LAND"
    fill = {"rung": request["rung"], "brief_digest": request["brief_digest"],
            "findings_digest": request["findings_digest"], "text": text}
    return panel._resume_native_president(board, stream_dir=stream, fill=fill, binding={}), findings


def test_native_fill_resume_with_a_counted_heartbeat_gemini_leg_succeeds(tmp_path):
    """claude N4: rebuilt legs lose their evidence; a COUNTED heartbeat Gemini leg must
    rebuild to the same findings and resume. Mutation: treating an evidence-less rebuilt
    leg as an uncounted agy leg."""
    leg = _leg("The design is sound.\n\nAGREE", admission_class="locally_qualified")
    result, findings = _resume_round_trip(tmp_path, leg)
    assert result.president is not None and result.president_findings == findings


def test_native_fill_resume_with_an_uncounted_leg_fails_closed(tmp_path):
    from phase_loop_runtime import panel_invoker as panel
    leg = _leg("The design is sound.\n\nAGREE", admission_class=None)
    with pytest.raises(panel.PresidentPolicyError):
        _resume_round_trip(tmp_path, leg)


def test_agy_profile_evidence_alone_identifies_the_leg():
    """claude N5: no monitoring record, but the owned agy profile ran it."""
    from phase_loop_runtime import panel_invoker as panel
    leg = panel.PanelLegResult(leg="gemini", status="OK", text="Fine.\nAGREE")
    object.__setattr__(leg, "_harden_isolation_evidence", {"provider_isolation_profile": gh.PROFILE_ID})
    assert q.counts_toward_landing(leg) is False


def test_heartbeat_creates_a_missing_stream_dir_private(tmp_path):
    """claude N7: the heartbeat never creates the board's stream directory world-readable."""
    stream = tmp_path / "new-stream"
    q.board_heartbeat(stream)("agy_qualification_lock_wait")
    assert stat.S_IMODE(stream.stat().st_mode) == 0o700


def test_cancellation_is_never_counted_as_a_transient(world, monkeypatch):
    """claude r3: the contract says cancellation is not counted. Drive the REAL qualify_image
    with a cancelled operation: no transient counter, no failed entry."""
    monkeypatch.setattr(q, "qualify_image", _REAL_QUALIFY)
    cancel = threading.Event()

    def run_operation(operation, root, *a, **k):
        cancel.set()
        root.mkdir(parents=True)
        exc = q.QualificationFailure(q.CANCELLED)
        q.write_failure(root, exc, "helper_observation", q.HelperObserver("0" * 64, {}), {})
        raise exc

    monkeypatch.setattr(q, "run_operation", run_operation)
    with pytest.raises(ValueError, match=q.CANCELLED):
        _ensure(world, cancel_event=cancel)
    assert "transient" not in _entries(world) and "failed" not in _entries(world)


def test_requalify_once_failure_is_recorded_and_a_later_board_runs_nothing(world, monkeypatch):
    q._REQUALIFIED.clear()
    monkeypatch.setattr(prov, "_Transport", lambda: world.transport)
    world.outcome = {"status": "failed", "operation": "completion",
                     "reason": "operation_validation_failed"}
    with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
        q.requalify_once(world.env)
    assert "failed" in _entries(world)
    assert world.counter.qualify == 1
    q._REQUALIFIED.clear()  # the second board is a new process
    with pytest.raises(ValueError, match=q.SELF_QUALIFICATION_FAILED):
        q.requalify_once(world.env)
    assert world.counter.qualify == 1
