"""agy first-use self-qualification (agent-harness#1076).

One falsifier per invariant of plans/detailed-agy-selfqual-1076-20260927.md (I1-I6,
D1-D4) and per follow-up the president carried from agent-harness#1118 (claude 5.1-5.8,
section 2, section 3). Each test names the mutation that turns it red.

Nothing here reaches the network or a model: the release listing and archives are
served by an in-memory transport, help measurement and the three live operations are
replaced by counting fakes, and store ownership / machine-id are injected.
"""
from __future__ import annotations

from hashlib import sha256
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

import pytest

q = pytest.importorskip("phase_loop_runtime.agy_qualification")

from phase_loop_runtime import agy_provenance as prov  # noqa: E402
from phase_loop_runtime import gemini_heartbeat as gh  # noqa: E402

MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
F_ADD_SEALS, F_GET_SEALS = 1033, 1034
F_SEAL_SEAL, F_SEAL_SHRINK, F_SEAL_GROW, F_SEAL_WRITE, F_SEAL_FUTURE_WRITE = 0x1, 0x2, 0x4, 0x8, 0x10


# ----------------------------------------------------------------------------- fixtures

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
            "assets": [{"name": asset, "browser_download_url": url,
                        "digest": digest or "sha256:" + sha256(archive).hexdigest()}],
        })

    def open(self, url, *, accept):
        self.calls.append(url)
        if self.fail is not None:
            raise self.fail
        if url.startswith(f"https://{prov.API_HOST}/"):
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

    def fake_qualify(verified, help_bytes, *, cancel_event=None, heartbeat=None, store=None):
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
    assert sorted(_entries(world)) == ["member_cache", "provenance", "qualified"]


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
        assert prov.read_member(io.BytesIO(archive), asset)[0] == world.digest
    else:
        with pytest.raises(prov.ProvenanceError):
            prov.read_member(io.BytesIO(archive), asset)


def test_member_digest_is_returned_only_after_the_archive_digest_matches(world):
    archive = _archive([("antigravity", world.image, tarfile.REGTYPE)])
    asset = prov.ReleaseAsset("1.2.99", HOST.asset, "u", "0" * 64)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        prov.read_member(io.BytesIO(archive), asset)


# --------------------------------------------------------------- I1 after verification

def test_path_swap_after_provenance_still_executes_the_verified_bytes(world, monkeypatch):
    """I1 TOCTOU. Mutation: re-opening the PATH file after provenance (a second open)."""
    opens = []
    real_read = gh._read_image
    monkeypatch.setattr(gh, "_read_image", lambda path: opens.append(path) or real_read(path))
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


def test_worker_refuses_sealed_unverified_bytes_without_provenance(world, monkeypatch):
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


@pytest.mark.parametrize("change", ["version", "route_core_digest"])
def test_worker_gate_and_member_cache_are_bound_to_the_runtime_identity(world, monkeypatch, change):
    """Worker bypass: a provenance entry differing only in __version__ or one ROUTE_CORE
    digest does not admit, and forces a fresh download. Mutation: keying either on the
    image digest alone."""
    _ensure(world)
    real = q.runtime_identity()
    other = dict(real, route_core=dict(real["route_core"]))
    if change == "version":
        other["version"] = "0.0.0"
    else:
        other["route_core"]["agy_provenance.py"] = "0" * 64
    monkeypatch.setattr(q, "runtime_identity", lambda package_dir=None: other)
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
    with pytest.raises(gh.AdmissionMiss):
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
    with pytest.raises(gh.AdmissionMiss):
        q.lookup(world.env, world.image, str(world.agy), store=q.Store(euid=os.geteuid() + 1))


def test_store_copied_from_another_host_is_absent(world, monkeypatch):
    _ensure(world)
    q._HELP_MEMO.clear()
    other = "b" * 32
    src = q.Store().host_dir
    dst = q.Store(machine_id=other).host_dir
    dst.mkdir(mode=0o700)
    for path in src.iterdir():
        (dst / path.name).write_bytes(path.read_bytes())
        (dst / path.name).chmod(0o600)
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": other)
    with pytest.raises(gh.AdmissionMiss):
        _admit(world)
    # the copied entry, renamed into the other host's slot, still fails its MAC
    for path in dst.iterdir():
        if path.name.startswith(("provenance-", "qualified-")):
            kind = path.name.split("-", 1)[0]
            twin = next(p for p in src.iterdir() if p.name.startswith(kind + "-"))
            path.write_bytes(twin.read_bytes())
    with pytest.raises(gh.AdmissionMiss):
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
    with pytest.raises(gh.AdmissionMiss):
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
    with pytest.raises(gh.AdmissionMiss):
        _admit(world)
    # the same bytes relabelled as a failed entry: its type is in the MAC context
    failed = store._path("failed", store._failed_context(world.digest, HOST, q.runtime_identity()))
    failed.write_text(json.dumps(dict(raw, type="failed")))
    failed.chmod(0o600)
    assert store.get_failed(world.digest, HOST, q.runtime_identity()) is None


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
    with pytest.raises(gh.AdmissionMiss):
        _admit(world)
    assert world.counter.help == 0


# ------------------------------------------------------------------------------ D2 key

@pytest.mark.parametrize("field", ["version", "route_core", "profile_id", "platform", "help"])
def test_record_differing_in_one_key_field_is_absent(world, monkeypatch, field):
    """D2. Mutation: dropping that field from the qualified entry's MAC context."""
    _ensure(world)
    q._HELP_MEMO.clear()
    real = q.runtime_identity()
    if field == "version":
        monkeypatch.setattr(q, "runtime_identity", lambda package_dir=None: dict(real, version="9.9.9"))
    elif field == "route_core":
        rc = dict(real["route_core"], **{"gemini_heartbeat.py": "0" * 64})
        monkeypatch.setattr(q, "runtime_identity", lambda package_dir=None: dict(real, route_core=rc))
    elif field == "profile_id":
        monkeypatch.setattr(gh, "PROFILE_ID", "agy_memfd_home_deny_all_v2")
    elif field == "platform":
        monkeypatch.setattr(prov, "detect_platform", lambda **_: prov.HostPlatform("linux", "x64", "musl"))
    elif field == "help":
        monkeypatch.setattr(q, "_run_help", lambda verified, env: b"different help\n")
    with pytest.raises(gh.AdmissionMiss):
        _admit(world)


def test_record_for_image_a_under_image_b_lookup_name_is_absent(world):
    _ensure(world)
    store = q.Store()
    host, runtime = HOST, q.runtime_identity()
    other = sha256(b"image B").hexdigest()
    for kind, name_a, name_b in (
        ("provenance", {**store._base(world.digest, host.name, runtime), "asset": host.asset},
         {**store._base(other, host.name, runtime), "asset": host.asset}),
        ("qualified", store._qualified_contexts(world.digest, "x", host, runtime)[0],
         store._qualified_contexts(other, "x", host, runtime)[0]),
    ):
        store._path(kind, name_b).write_bytes(store._path(kind, name_a).read_bytes())
        store._path(kind, name_b).chmod(0o600)
    assert store.get_provenance(other, host, runtime) is None


def test_verifier_and_runtime_share_one_route_core_tuple():
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
    if not script.is_file():
        pytest.skip("scripts/ is repository source")  # pragma: no cover - sdist layout only
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image_rc", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ROUTE_CORE is q.ROUTE_CORE
    assert {"gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py"} <= set(q.ROUTE_CORE)
    assert "agy_watch.py" not in q.ROUTE_CORE


def test_runtime_identity_is_the_installed_package_never_the_reviewed_tree(world, tmp_path, monkeypatch):
    """claude section 3: boards admit with the installed base runtime. Mutation: resolving
    route-core from the cwd / repo_dir."""
    before = q.runtime_identity()
    fake = tmp_path / "reviewed" / "phase-loop-runtime/src/phase_loop_runtime"
    fake.mkdir(parents=True)
    for name in q.ROUTE_CORE:
        (fake / name).write_text("# reviewed tree\n")
    monkeypatch.chdir(fake)
    monkeypatch.syspath_prepend(str(fake.parent))
    assert q.runtime_identity() == before


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


@pytest.mark.parametrize("stage,result,expected", [
    ("admission_observation", "OK", "transient"),
    ("launch", None, "transient"),
    ("validation", "UNAVAILABLE", "transient"),  # completion the provider did not answer (5xx/quota/auth)
    ("validation", "OK", "failed"),
    ("cleanup_observation", "OK", "failed"),
])
def test_failure_classification(tmp_path, stage, result, expected):
    (tmp_path / "failure.json").write_text(json.dumps({"stage": stage}))
    if result is not None:
        (tmp_path / "terminal.json").write_text(json.dumps({"result": {"status": result}}))
    assert q._classify_failure(tmp_path, "completion") == expected


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


# --------------------------------------------------------------------- I3 concurrency

_CHILD = textwrap.dedent('''
    import json, os, sys, time
    from hashlib import sha256
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from phase_loop_runtime import agy_qualification as q, agy_provenance as prov, gemini_heartbeat as gh
    tmp = Path(sys.argv[2]); mode = sys.argv[3]
    q.read_machine_id = lambda path="/etc/machine-id": "a" * 32
    prov.detect_platform = lambda **_: prov.HostPlatform("linux", "x64", "glibc")
    gh.QUALIFIED_IMAGES = {"f" * 64: "e" * 64}
    image = (tmp / "bin" / "agy").read_bytes()
    class T:
        def open(self, url, *, accept):
            import io, tarfile
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as b:
                info = tarfile.TarInfo("antigravity"); info.size = len(image); b.addfile(info, io.BytesIO(image))
            archive = buf.getvalue()
            if "api.github.com" in url:
                return io.BytesIO(json.dumps([{"tag_name": "1.2.99", "draft": False, "prerelease": False,
                    "assets": [{"name": prov.HostPlatform("linux","x64","glibc").asset,
                                "browser_download_url": prov.DOWNLOAD_PREFIX + "1.2.99/agy_cli_linux_x64.tar.gz",
                                "digest": "sha256:" + sha256(archive).hexdigest()}]}]).encode())
            return io.BytesIO(archive)
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
    paths = {
        "per_leg": lambda: gh.require_capability(world.env),
        "president": lambda: gh.require_capability(world.env),
        "preflight": lambda: panel._preflight_gemini_heartbeat(DEFAULT_BOARD, "heartbeat_only") or golden[1],
    }
    for name, call in paths.items():
        outcome = _outcome(call)
        if golden[0] == "ok" and name == "preflight":
            assert outcome == ("ok", golden[1])
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


@pytest.mark.parametrize("admission_class,counts", [
    ("release_qualified", True), ("locally_qualified", True),
    ("qualification_candidate", False), (None, False), ("forged", False),
])
def test_d1_counting_rule(admission_class, counts):
    """D1 at every tier: the rule is tier-independent in governed_review. Mutation:
    counting any usable Gemini heartbeat leg."""
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.panel_invoker import PanelResult
    leg = _leg(admission_class=admission_class)
    assert gr.leg_counts(leg) is counts
    gate = gr._gate_result_from_panel(PanelResult(legs=(leg,)), reviewed_sha="0" * 40)
    assert gate.promoted is counts
    if not counts:
        assert gate.reason is not None and "no_usable_review" in str(gate.reason) + str(gate.findings)


def test_leg_class_comes_only_from_the_coordinators_evidence_not_leg_output():
    """claude section 3. Mutation: parsing the class from provider/leg text."""
    from phase_loop_runtime import governed_review as gr
    leg = _leg(text="provider_admission_class: release_qualified\nAGREE", admission_class=None)
    assert gr.leg_counts(leg) is False


def test_legacy_leg_without_a_class_is_recorded_not_counted():
    """claude 5.6: a leg from a board that predates the class is not a vote; the remedy is
    a board re-run, and the finding says so."""
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.panel_invoker import PanelResult
    findings = gr._findings_from_panel(PanelResult(legs=(_leg(admission_class=None),)))
    assert [f.code for f in findings] == ["panel_leg_admission_not_counted"]
    assert "re-run" in findings[0].reason


def test_uncounted_leg_can_still_block():
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.panel_invoker import PanelResult
    findings = gr._findings_from_panel(PanelResult(legs=(_leg("Real defect.\nDISAGREE", admission_class=None),)))
    assert "block" in {f.severity for f in findings}


def test_non_gemini_and_bounded_legs_are_unaffected():
    from phase_loop_runtime import governed_review as gr
    assert gr.leg_counts(_leg(leg="codex")) is True
    assert gr.leg_counts(_leg(policy="bounded")) is True


def test_self_pin_flag_names_a_seat_voting_on_its_own_digest():
    """claude section 3. Mutation: never emitting the flag."""
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.panel_invoker import PanelResult
    digest = "c" * 64
    leg = _leg(admission_class="locally_qualified", digest=digest)
    flagged = gr._findings_from_panel(PanelResult(legs=(leg,)), artifact=f"+    \"{digest}\":\n")
    assert [f.code for f in flagged if f.code == "gemini_seat_reviews_its_own_pin"]
    clean = gr._findings_from_panel(PanelResult(legs=(leg,)), artifact="no digests here")
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
    with pytest.raises(gh.AdmissionMiss):
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
    tree = tmp_path / "tree"
    for rel in ("phase-loop-runtime/src/phase_loop_runtime", "phase-loop-runtime/scripts", "plans/evidence"):
        src = root / rel
        if not src.is_dir():
            pytest.skip("repository layout absent")  # pragma: no cover - sdist layout only
        import shutil
        shutil.copytree(src, tree / rel, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


class _Runner:
    def __init__(self, prs="[]"):
        self.calls, self.prs = [], prs

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ["gh", "pr", "list"]:
            return SimpleNamespace(stdout=self.prs, returncode=0)
        if argv[:2] == ["git", "-C"] and "worktree" in argv and "add" in argv:
            return SimpleNamespace(stdout="", returncode=0)
        return SimpleNamespace(stdout="", returncode=0)


def test_watch_opens_nothing_on_a_platform_it_cannot_propose(tmp_path):
    from phase_loop_runtime import agy_watch
    runner, out = _Runner(), []
    assert agy_watch.main(repo=tmp_path, runner=runner, host=prov.HostPlatform("linux", "arm64", "glibc"),
                          out=out.append) == 0
    assert runner.calls == [] and "platform_not_proposed" in out[0]


def test_watch_second_tick_for_the_same_version_is_a_no_op(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_watch
    tree = _watch_repo(tmp_path)
    t = FakeTransport()
    t.add("9.9.9", b"new agy")
    base = agy_watch.route_core_digest(tree)
    runner = _Runner(prs=json.dumps([{"number": 1, "body": f"x\n{agy_watch.MARKER} {base}\n"}]))
    out = []
    assert agy_watch.main(repo=tmp_path, runner=runner, host=HOST, transport=t, workdir=tmp_path,
                          out=out.append) == 0
    assert "up_to_date" in out[0]
    assert not [call for call in runner.calls if call[:3] in (["gh", "pr", "merge"], ["git", "merge"])]
    assert not [c for c in t.calls if "releases/download" in c]  # no archive fetched


def test_watch_never_merges_and_skips_a_pinned_version(tmp_path):
    from phase_loop_runtime import agy_watch
    tree = _watch_repo(tmp_path)
    pinned = sorted(agy_watch.pinned_versions(tree))[-1]
    t = FakeTransport()
    t.add(pinned, b"already pinned")
    runner, out = _Runner(), []
    agy_watch.main(repo=tmp_path, runner=runner, host=HOST, transport=t, workdir=tmp_path, out=out.append)
    assert "already_pinned" in out[0]
    assert not [call for call in runner.calls if call[:3] in (["gh", "pr", "merge"], ["git", "merge"])]


def test_watch_record_passes_route_core_on_its_prepared_tree(tmp_path):
    """The watch's tree edits put the new digest in the TREE's release constant (so the
    tree's own worker gate admits it -- claude 5.2), and the summarized record passes
    ``verify_qualified_agy_image.py --route-core`` against that tree."""
    import ast
    from phase_loop_runtime import agy_watch
    tree = _watch_repo(tmp_path)
    image, help_sha = sha256(b"watch image").hexdigest(), sha256(b"watch help").hexdigest()
    agy_watch.edit_constants(tree, image, "0" * 64, "9.9.9")
    agy_watch.edit_constants(tree, image, help_sha, "9.9.9")  # idempotent re-edit
    literal = next(node.value for node in ast.parse((tree / agy_watch.HEARTBEAT).read_text()).body
                   if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "QUALIFIED_IMAGES")
    constants = ast.literal_eval(literal)
    assert constants[image] == help_sha and list(constants).count(image) == 1
    catalog = json.loads((tree / agy_watch.CATALOG).read_text())
    assert [m for m in catalog["routes"]["gemini_heartbeat_linux_x64"]["images"] if m["release_version"] == "9.9.9"]
    # receipts shaped like the newest committed record, pinning the prepared tree
    verifier = tree / "phase-loop-runtime/scripts/verify_qualified_agy_image.py"
    spec_src = subprocess.run([sys.executable, "-c",
                               "import runpy,json,sys; m=runpy.run_path(sys.argv[1]);"
                               "print(json.dumps(m['actual_source_hashes']()))", str(verifier)],
                              capture_output=True, text=True, check=True)
    sources = json.loads(spec_src.stdout)
    template_name = catalog["routes"]["gemini_heartbeat_linux_x64"]["images"][-2]["record"]
    template = json.loads((tree / "plans/evidence" / template_name).read_text())
    series = tmp_path / "series"
    for row in template["records"]:
        receipt = json.loads(json.dumps(row))
        receipt.update(image_sha256=image, help_sha256=help_sha, source_sha256=sources,
                       request=row["request_digests"])
        receipt["profile"] = dict(row["profile"], image_sha256=image)
        (series / row["operation"]).mkdir(parents=True)
        (series / row["operation"] / "qualification.json").write_text(json.dumps(receipt))
    asset = prov.ReleaseAsset("9.9.9", HOST.asset, "u", "1" * 64)
    record = agy_watch.summarize(tree, series, asset, image, help_sha)
    (tree / "plans/evidence/agy-9.9.9-linux-x64-qualification.json").write_text(json.dumps(record, indent=2))
    # the older members' records pin the original tree; only the new one is under test
    catalog["routes"]["gemini_heartbeat_linux_x64"]["images"] = [
        m for m in catalog["routes"]["gemini_heartbeat_linux_x64"]["images"] if m["release_version"] == "9.9.9"]
    (tree / agy_watch.CATALOG).write_text(json.dumps(catalog))
    text = (tree / agy_watch.HEARTBEAT).read_text()
    start = text.index("QUALIFIED_IMAGES = {")
    end = text.index("}\nPROFILE_ID", start) + 1
    (tree / agy_watch.HEARTBEAT).write_text(
        text[:start] + f'QUALIFIED_IMAGES = {{\n    "{image}":\n        "{help_sha}",\n}}' + text[end:])
    sources = json.loads(subprocess.run([sys.executable, "-c",
                                         "import runpy,json,sys; m=runpy.run_path(sys.argv[1]);"
                                         "print(json.dumps(m['actual_source_hashes']()))", str(verifier)],
                                        capture_output=True, text=True, check=True).stdout)
    record["source_sha256"] = sources
    (tree / "plans/evidence/agy-9.9.9-linux-x64-qualification.json").write_text(json.dumps(record, indent=2))
    result = subprocess.run([sys.executable, str(verifier), "--route-core"], cwd=tree, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["qualified_releases"] == ["9.9.9"]


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
    """The watch requalifies every catalog member on the prepared tree (adding a member
    edits a route-core file every record pins); an existing member's re-fetched image
    must equal its committed record. Mutation: trusting the upstream bytes."""
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
        agy_watch.main(repo=tmp_path, runner=_Runner(), host=HOST, base_ref="HEAD")
