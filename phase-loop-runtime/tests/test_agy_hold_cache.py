"""AGYFRESH HOLD, lane SL-4 (HOLD-CACHE): the harness cache (AGYFRESH §2.5, §2.8; EC-HOLD-10).

``agy_hold.retain`` keeps an admitted subject image as ``<Store.host_dir>/held/<sha256>``
after ``admit_seat(first_use=True)`` admits the subject. It never waits for the store lock
and never raises. Pruning keeps ``HELD_KEEP`` images by authenticated version, a corrupt
file is unlinked, and ``agy-qualification clear --all`` removes ``held/``. Every mutation
takes the store lock and works descriptor-relative from the reader's anchor.

Cases enter through ``admit_seat(first_use=True)`` (the board preflight) and ``cli_main``
``clear`` over a real store directory under ``tmp_path``; the cases that call
``agy_hold`` directly are additional. Help measurement is a counting fake; provenance never
reaches the network; nothing executes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
import sys
import threading
import time
import tracemalloc
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_hold
from phase_loop_runtime import agy_integrity
from phase_loop_runtime import agy_provenance as prov
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import seat_subject

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "memfd_create"),
    reason="Linux sealed-memfd seat admission",
)

MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
HELP = b"synthetic help\n"
#: AGYFRESH §1.2: one sealed image plus at most 2 MiB (as tests/test_agy_size_bounds.py).
OVERHEAD_CEILING = 2 * 1024 * 1024


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _image(tag: str, size: int = 4096) -> bytes:
    head = f"#!/bin/sh\necho synthetic agy {tag}\n".encode()
    return head + b"#" * max(0, size - len(head))


def _no_network(*_args, **_kwargs):
    raise prov.ProvenanceError(prov.UNVERIFIED)


def _open_fds():
    return sorted(os.listdir("/proc/self/fd"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A subject on PATH, an empty vendor store, a qualification store under ``tmp_path``
    and a catalog the test fills."""
    previous = os.umask(0o022)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(prov, "find_provenance", _no_network)
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    monkeypatch.setattr(q, "_LAST_KNOWN_GOOD_PROVIDER", None)
    monkeypatch.setattr(q, "_HELP_MEMO", {})
    monkeypatch.setattr(q, "_REQUALIFIED", set())
    monkeypatch.setattr(agy_hold, "_WALK_ROOT", tmp_path)
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    monkeypatch.setattr(agy_hold, "VENDOR_STORES", (vendor,))
    members: list[dict] = []
    qualified: dict[str, str] = {}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", qualified)
    monkeypatch.setattr(gh, "catalog_members", lambda path=None: [dict(item) for item in members])
    bindir = tmp_path / "bin"
    bindir.mkdir()
    agy = bindir / "agy"
    helps: list[str] = []

    def fake_help(image, env, **_kwargs):
        helps.append(image.sha256)
        return HELP

    monkeypatch.setattr(q, "_run_help", fake_help)
    w = SimpleNamespace(tmp=tmp_path, vendor=vendor, agy=agy, helps=helps, members=members,
                        env={"PATH": str(bindir), "HOME": str(tmp_path / "home")})

    def subject(data):
        agy.write_bytes(data)
        agy.chmod(0o755)
        return data

    def member(data, version):
        members.append({"release_version": version, "image_sha256": _sha(data), "help_sha256": _sha(HELP)})
        qualified[_sha(data)] = _sha(HELP)
        return _sha(data)

    def store():
        value = q.Store()
        value.create()
        return value

    def held():
        return q.Store().host_dir / agy_hold.HELD_DIRNAME

    def cached():
        directory = held()
        return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []

    def put_cache(data, *, name=None):
        value = store()
        directory = value.host_dir / agy_hold.HELD_DIRNAME
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / (name or _sha(data))
        target.write_bytes(data)
        target.chmod(0o600)
        return target

    def seed_local(data, version, *, qualified_entry=True):
        value = store()
        key = q.agy_profile_digest()
        asset = SimpleNamespace(name=HOST.asset, version=version, digest="sha256:" + "0" * 64)
        value.put_provenance(SimpleNamespace(image_sha256=_sha(data), platform=HOST.name, asset=asset), key)
        if qualified_entry:
            value.put_qualified(_sha(data), _sha(HELP), HOST, key, version)

    def config(text):
        path = tmp_path / "config" / "agent-harness" / "advisor-boards.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    w.subject, w.member, w.store, w.held, w.cached = subject, member, store, held, cached
    w.put_cache, w.seed_local, w.config = put_cache, seed_local, config
    try:
        yield w
    finally:
        os.umask(previous)


def _preflight(world, **kwargs):
    """The board preflight's admission: ``admit_seat(first_use=True)``."""
    return q.admit_seat(world.env, world.agy, first_use=True, **kwargs)


def _admit(world, **kwargs):
    admission = _preflight(world, **kwargs)
    try:
        return admission.source, admission.image.sha256
    finally:
        admission.close()


def _sealed(data):
    return gh.VerifiedImage.from_bytes(data)


def _retain(world, data, **kwargs):
    image = _sealed(data)
    try:
        agy_hold.retain(image, world.store(), **kwargs)
    finally:
        image.close()


# ------------------------------------------------------------------- retain writes

def test_ec_hold_10_a_subject_admission_retains_its_image_0600_in_a_0700_directory(world):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    assert _admit(world) == ("subject", _sha(data))
    target = world.held() / _sha(data)
    assert world.cached() == [_sha(data)]
    assert target.read_bytes() == data
    assert (target.stat().st_mode & 0o777, world.held().stat().st_mode & 0o777) == (0o600, 0o700)
    assert q.Store().status() == "ok"  # with held/ present


def test_ec_hold_10_retain_creates_the_store_when_it_is_absent(world):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    assert q.Store().status() == "absent"
    _admit(world)
    assert q.Store().status() == "ok" and world.cached() == [_sha(data)]


def test_ec_hold_10_a_locally_qualified_subject_is_retained_after_first_use(world):
    data = world.subject(_image("local 1.6.0"))
    world.seed_local(data, "1.6.0", qualified_entry=False)
    calls = []

    def passing(image, help_bytes, **_kwargs):
        calls.append(image.sha256)
        return {"status": "passed"}

    assert _admit(world, qualify=passing) == ("subject", _sha(data))
    assert calls == [_sha(data)] and world.cached() == [_sha(data)]


def test_ec_hold_10_retain_streams_within_the_overhead_ceiling(world):
    data = os.urandom(24 * 1024 * 1024)
    image = _sealed(data)
    store = world.store()
    try:
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            agy_hold.retain(image, store)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    finally:
        image.close()
    assert (world.held() / _sha(data)).read_bytes() == data
    assert peak < OVERHEAD_CEILING, peak


def test_ec_hold_10_a_second_retain_is_a_no_op(world):
    data = _image("member 1.5.3")
    world.member(data, "1.5.3")
    _retain(world, data)
    before = os.stat(world.held() / _sha(data))
    _retain(world, data)
    after = os.stat(world.held() / _sha(data))
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
    assert world.cached() == [_sha(data)]


# ------------------------------------------------------------------------ pruning

def test_ec_hold_10_a_third_image_prunes_by_version_never_the_one_just_retained(world):
    oldest, middle, newest = _image("member 1.5.3"), _image("member 1.5.4"), _image("member 1.5.5")
    for data, version in ((oldest, "1.5.3"), (middle, "1.5.4"), (newest, "1.5.5")):
        world.member(data, version)
    for data, stamp in ((middle, 4_000_000_000_000_000_000), (newest, 1_000_000_000)):
        os.utime(world.put_cache(data), ns=(stamp, stamp))  # mtime says the opposite
    _retain(world, oldest)  # the oldest version, retained now
    assert world.cached() == sorted([_sha(oldest), _sha(newest)])


def test_ec_hold_10_a_file_with_no_authenticated_version_is_pruned_first(world):
    unknown, middle, oldest = _image("unknown"), _image("member 1.5.4"), _image("member 1.5.3")
    world.member(middle, "1.5.4")
    world.member(oldest, "1.5.3")
    world.put_cache(unknown)
    world.put_cache(middle)
    _retain(world, oldest)
    assert world.cached() == sorted([_sha(oldest), _sha(middle)])


def test_ec_hold_10_a_locally_qualified_version_counts_as_authenticated(world):
    local, member_old, member_new = _image("local 1.6.0"), _image("member 1.5.3"), _image("member 1.5.4")
    world.seed_local(local, "1.6.0")
    world.member(member_old, "1.5.3")
    world.member(member_new, "1.5.4")
    world.subject(member_old)
    world.put_cache(local)
    world.put_cache(member_new)
    _admit(world)  # retains 1.5.3 through the production gate, with provenance versions
    assert world.cached() == sorted([_sha(member_old), _sha(local)])


def test_ec_hold_10_a_corrupt_cache_file_is_unlinked_and_skipped(world):
    good, other = _image("member 1.5.3"), _image("member 1.5.4")
    world.member(good, "1.5.3")
    world.member(other, "1.5.4")
    world.put_cache(b"not the bytes it is named by", name=_sha(other))
    _retain(world, good)
    assert world.cached() == [_sha(good)]


def test_ec_hold_10_a_leftover_temp_file_is_removed_under_the_lock(world):
    data = _image("member 1.5.3")
    world.member(data, "1.5.3")
    world.put_cache(b"partial", name=f".{'c' * 64}.{'d' * 16}.tmp")
    _retain(world, data)
    assert world.cached() == [_sha(data)]


# --------------------------------------------------------------- never fails, never waits

def test_ec_hold_10_retain_with_the_store_lock_held_elsewhere_skips(world):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    store = world.store()
    with store.lock():
        assert _admit(world) == ("subject", _sha(data))  # the admission still returns
    assert world.cached() == []


def test_ec_hold_10_retain_on_a_read_only_directory_swallows_the_error(world):
    if os.geteuid() == 0:
        pytest.skip("root writes a mode-0500 directory")
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    world.store()
    world.held().mkdir(mode=0o700)
    world.held().chmod(0o500)
    try:
        assert _admit(world) == ("subject", _sha(data))
        assert world.cached() == []
    finally:
        world.held().chmod(0o700)


def test_ec_hold_10_retain_never_raises_and_never_closes_the_image(world, monkeypatch):
    data = _image("member 1.5.3")
    image = _sealed(data)
    store = world.store()

    def broken(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(agy_hold, "_open_cache_store", broken)
    before = _open_fds()
    try:
        assert agy_hold.retain(image, store) is None
        assert image.fd is not None and os.pread(image.fd, 16, 0) == data[:16]
    finally:
        image.close()
    assert sorted(set(_open_fds()) - set(before)) == []


# ------------------------------------------------------------------ symlinks and races

def test_ec_hold_10_a_symlink_named_like_the_digest_is_not_followed(world):
    data = _image("member 1.5.3")
    world.member(data, "1.5.3")
    world.store()
    world.held().mkdir(mode=0o700)
    outside = world.tmp / "outside"
    outside.write_bytes(b"outside")
    (world.held() / _sha(data)).symlink_to(outside)
    _retain(world, data)
    assert outside.read_bytes() == b"outside"
    assert (world.held() / _sha(data)).is_symlink()


def test_ec_hold_10_pruning_neither_follows_nor_unlinks_through_a_symlink(world):
    newest, middle, oldest = _image("member 1.5.5"), _image("member 1.5.4"), _image("member 1.5.3")
    for data, version in ((newest, "1.5.5"), (middle, "1.5.4"), (oldest, "1.5.3")):
        world.member(data, version)
    world.put_cache(middle)
    outside = world.tmp / "outside"
    outside.write_bytes(newest)
    (world.held() / _sha(newest)).symlink_to(outside)  # a link named like a member's digest
    _retain(world, oldest)
    assert outside.read_bytes() == newest
    assert (world.held() / _sha(newest)).is_symlink()
    assert sorted(p.name for p in world.held().iterdir() if not p.is_symlink()) == sorted(
        [_sha(oldest), _sha(middle)])


def test_ec_hold_10_a_name_replaced_between_judgement_and_unlink_is_not_unlinked(world, monkeypatch):
    victim, keeper, oldest = _image("member 1.5.3"), _image("member 1.5.5"), _image("member 1.5.2")
    for data, version in ((victim, "1.5.3"), (keeper, "1.5.5"), (oldest, "1.5.2")):
        world.member(data, version)
    world.put_cache(victim)
    world.put_cache(keeper)
    replacement = b"replaced after judgement"
    real = agy_hold._fd_sha256
    target = world.held() / _sha(victim)

    def judge_then_replace(fd, buffer):
        digest = real(fd, buffer)
        if os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(target):
            staged = world.tmp / "replacement"
            staged.write_bytes(replacement)
            os.rename(staged, target)
        return digest

    monkeypatch.setattr(agy_hold, "_fd_sha256", judge_then_replace)
    _retain(world, oldest)
    assert target.read_bytes() == replacement  # judged as a victim, but no longer that inode


def test_ec_hold_10_concurrent_retain_and_clear_leave_a_complete_file_or_none(world):
    data = _image("member 1.5.3", 4 * 1024 * 1024)
    world.member(data, "1.5.3")
    store = world.store()
    for _round in range(8):
        image = _sealed(data)
        barrier = threading.Barrier(2)
        errors = []

        def retain():
            barrier.wait()
            agy_hold.retain(image, store)

        def clear():
            barrier.wait()
            try:
                agy_hold.clear_held(store)
            except Exception as exc:  # noqa: BLE001 - recorded and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=retain), threading.Thread(target=clear)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        image.close()
        assert errors == []
        names = world.cached()
        assert names in ([], [_sha(data)])  # no temp file, no partial file
        if names:
            assert (world.held() / names[0]).read_bytes() == data


# ------------------------------------------------------------------- the reader's limit

@pytest.mark.parametrize("how", ["cleared", "pruned"])
@pytest.mark.parametrize("other", [False, True])
def test_ec_hold_10_a_reader_holding_a_pruned_or_cleared_file_rejects_it(world, monkeypatch, how, other):
    """The B2 limit: the cache file is removed while the hold reads it. That file is
    rejected and the walk continues; with no other candidate the original refusal stands."""
    cached = _image("member 1.5.4", 3 * 1024 * 1024)
    world.member(cached, "1.5.4")
    target = world.put_cache(cached)
    vendor_member = _image("member 1.5.3")
    world.member(vendor_member, "1.5.3")
    if other:
        directory = world.vendor / f"1.5.3-{_sha(vendor_member)[:16]}"
        directory.mkdir()
        (directory / "agy").write_bytes(vendor_member)
        (directory / "agy").chmod(0o755)
    world.subject(_image("unqualified subject"))
    store = q.Store()
    real_readv = os.readv
    hit = []

    def remove_while_read(fd, buffers):
        count = real_readv(fd, buffers)
        if not hit and os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(target):
            hit.append(True)
            if how == "cleared":
                agy_hold.clear_held(store)
            else:
                monkeypatch.setattr(agy_hold, "HELD_KEEP", 1)
                anchor = agy_hold.open_anchor(store.host_dir)
                try:
                    held = os.open(agy_hold.HELD_DIRNAME, os.O_RDONLY | os.O_DIRECTORY, dir_fd=anchor)
                    try:
                        agy_hold._prune(held, agy_hold._list_names(held), "0" * 64, None,
                                        bytearray(1024 * 1024))
                    finally:
                        os.close(held)
                finally:
                    os.close(anchor)
        return count

    monkeypatch.setattr(os, "readv", remove_while_read)
    if other:
        assert _admit(world) == ("lkg", _sha(vendor_member))
    else:
        with pytest.raises(ValueError, match=f"^{prov.UNVERIFIED}$"):
            _preflight(world)
    assert hit and not target.exists()


# ------------------------------------------------------------------------- clear

def test_ec_hold_10_clear_keeps_the_cache_and_clear_all_removes_it(world, capsys):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    store = q.Store()
    store.note_fetch(_sha(data), HOST, time.time())
    assert world.cached() == [_sha(data)]
    assert q.cli_main(SimpleNamespace(action="clear", all=False)) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 0}
    assert world.cached() == [_sha(data)] and "fetch_ledger" in store.entries()
    assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["held_removed"] == 1 and printed["removed"] >= 1
    assert not world.held().exists() and "fetch_ledger" not in store.entries()
    assert store.status() == "ok"


# --------------------------------------------------------------------------- B7

def test_ec_hold_10_b7_no_file_for_a_managed_subject(world, monkeypatch):
    releases = world.tmp / "releases"
    native = releases / "sync-0" / "native" / "agy"
    native.parent.mkdir(parents=True)
    data = _image("member 1.5.3")
    native.write_bytes(data)
    native.chmod(0o755)
    world.member(data, "1.5.3")
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", releases)
    admission = q.admit_seat(world.env, native, first_use=True)
    admission.close()
    assert admission.source == "subject" and world.cached() == []


def test_ec_hold_10_b7_no_file_with_the_hold_disabled(world):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    world.config("[agy]\nhold = false\n")
    assert _admit(world) == ("subject", _sha(data))
    assert world.cached() == []


def test_ec_hold_10_b7_no_file_for_a_denied_digest(world):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    world.config(f'[agy]\nhold_deny = ["{_sha(data)}"]\n')
    assert _admit(world) == ("subject", _sha(data))
    assert world.cached() == []


def test_ec_hold_10_b7_no_retain_on_a_spawn_or_heartbeat_admission(world):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    agy_integrity.admit_for_seat(str(world.agy), world.env).close()
    gh.admit(world.env).close()
    assert world.cached() == []


def test_ec_hold_10_b7_no_retain_after_a_held_admission(world):
    held_member = _image("member 1.5.3")
    world.member(held_member, "1.5.3")
    directory = world.vendor / f"1.5.3-{_sha(held_member)[:16]}"
    directory.mkdir()
    (directory / "agy").write_bytes(held_member)
    (directory / "agy").chmod(0o755)
    world.subject(_image("unqualified subject"))
    assert _admit(world) == ("lkg", _sha(held_member))
    assert world.cached() == []


# ------------------------------------------------------------------ B1 and end to end

def test_ec_hold_10_b1_a_newer_image_arriving_through_retain_wins_the_next_hold(world):
    older, newer = _image("member 1.5.3"), _image("member 1.5.4")
    world.member(older, "1.5.3")
    world.member(newer, "1.5.4")
    world.put_cache(older)
    world.subject(newer)
    _admit(world)  # retains 1.5.4
    world.subject(_image("unqualified subject"))
    assert _admit(world) == ("lkg", _sha(newer))


def test_ec_hold_10_end_to_end_a_retained_image_is_the_hold_on_route_1(world):
    """No vendor store: the preflight retains the admitted member; the PATH agy is then
    replaced by an unqualified build, and the seat-profile route holds the retained image."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    assert _admit(world) == ("subject", _sha(data))
    world.subject(_image("unqualified update 1.5.4"))
    evidence = {}
    image = agy_integrity.admit_for_seat(str(world.agy), world.env, evidence=evidence)
    try:
        assert os.pread(image.fd, 1 << 20, 0) == data
    finally:
        image.close()
    assert (evidence["provider_admission_source"], evidence["provider_image_sha256"],
            evidence["provider_hold_reason"]) == ("lkg", _sha(data), "subject_unqualified")


def test_ec_hold_10_the_cache_is_read_only_through_the_anchor(world):
    """The reader keeps its rules for written files: a cache file made group-writable after
    it was retained is not read."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    (world.held() / _sha(data)).chmod(0o620)
    world.subject(_image("unqualified update 1.5.4"))
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        agy_integrity.admit_for_seat(str(world.agy), world.env)


def test_store_entries_ignore_the_cache_directory(world):
    data = _image("member 1.5.3")
    world.member(data, "1.5.3")
    _retain(world, data)
    store = q.Store()
    assert store.status() == "ok" and store.entries() == [] and store.remove(q._ENTRY_TYPES) == 0
    assert world.cached() == [_sha(data)]


def test_try_lock_reports_a_busy_lock_without_waiting(world):
    store = world.store()
    with store.lock():
        with store.try_lock() as locked:
            assert locked is False
    with store.try_lock() as locked:
        assert locked is True


# ------------------------------------------------------------- the test-suite guard

def test_the_cache_is_inert_in_a_test_that_does_not_opt_in(tmp_path, monkeypatch):
    """tests/conftest.py points the anchor walk root at nothing, so a test that does not set
    ``agy_hold._WALK_ROOT`` itself neither reads nor writes a cache, on every host, whatever
    its temp directory: no store is created and no ``held/`` appears."""
    assert agy_hold._WALK_ROOT == agy_hold.Path("/nonexistent/agy-hold-anchor-off")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    data = _image("member 1.5.3")
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {_sha(data): _sha(HELP)})
    subject = tmp_path / "bin" / "agy"
    subject.parent.mkdir()
    subject.write_bytes(data)
    subject.chmod(0o755)
    admission = q.admit_seat({"PATH": str(subject.parent)}, subject, first_use=True)
    admission.close()
    assert admission.source == "subject"
    assert q.Store().status() == "absent" and not (tmp_path / "state").exists()
    store = q.Store()
    store.create()
    image = gh.VerifiedImage.from_bytes(data)
    try:
        agy_hold.retain(image, store)
    finally:
        image.close()
    assert not (store.host_dir / agy_hold.HELD_DIRNAME).exists()
    assert agy_hold.clear_held(store) == (0, ())



# ---------------------------------------------- round 3: the review's REQUIRED findings

def _snapshot(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


@pytest.mark.parametrize("ancestor", ["group_writable", "symlink"])
def test_ec_hold_10_a_refused_ancestor_with_an_absent_store_creates_nothing(world, monkeypatch, ancestor):
    """Finding 1: the existing ancestry is validated before anything is created."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    if ancestor == "group_writable":
        state = world.tmp / "unsafe-state"
        state.mkdir()
        state.chmod(0o775)
    else:
        real = world.tmp / "real-state"
        real.mkdir()
        state = world.tmp / "linked-state"
        state.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    assert q.Store().status() == "absent"
    before = _snapshot(world.tmp / ("unsafe-state" if ancestor == "group_writable" else "real-state"))
    assert _admit(world) == ("subject", _sha(data))  # the admission still returns
    after = _snapshot(world.tmp / ("unsafe-state" if ancestor == "group_writable" else "real-state"))
    assert before == after == []  # no store, no key, no lock, no held/


def test_ec_hold_10_a_refused_ancestor_with_an_existing_store_takes_no_lock(world, monkeypatch):
    """Finding 1: the writers' anchor is validated before the lock is opened, and the lock
    is opened relative to it; a refused anchor creates no lock file and writes nothing."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    store = world.store()
    lock = store.host_dir / "lock"
    assert not lock.exists()  # Store.create makes no lock
    state = world.tmp / "state"
    state.chmod(0o775)
    try:
        assert store.status() == "ok"
        assert _admit(world) == ("subject", _sha(data))
        assert not lock.exists() and not world.held().exists()
    finally:
        state.chmod(0o755)


def test_ec_hold_10_the_retain_lock_is_the_store_lock(world):
    """Opened relative to the verified anchor, it is still the one store lock: a holder of
    ``Store.lock`` (by path) makes ``retain`` skip, and the reverse."""
    data = _image("member 1.5.3")
    world.member(data, "1.5.3")
    store = world.store()
    with store.lock():
        _retain(world, data)
    assert world.cached() == []
    anchor = agy_hold._open_cache_store(store)
    try:
        with store.try_lock(dir_fd=anchor) as locked:
            assert locked is True
            with store.try_lock() as other:
                assert other is False
    finally:
        os.close(anchor)


def test_ec_hold_10_an_existing_cache_directory_must_be_0700(world):
    """Finding 3 (writer): an existing ``held/`` that is not the euid's 0700 refuses the
    write; its mode is not changed."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    world.store()
    world.held().mkdir(mode=0o700)
    world.held().chmod(0o755)
    assert _admit(world) == ("subject", _sha(data))
    assert world.cached() == [] and world.held().stat().st_mode & 0o777 == 0o755


def test_ec_hold_10_an_unusable_higher_version_never_displaces_a_usable_one(world):
    """Finding 3: pruning ranks only what the reader admits. A higher-version member whose
    exact bytes sit in a group-writable file is unlinked, and the usable lower version is
    kept, and is then the hold."""
    unusable, usable, new = _image("member 1.5.5"), _image("member 1.5.4"), _image("member 1.5.3")
    for data, version in ((unusable, "1.5.5"), (usable, "1.5.4"), (new, "1.5.3")):
        world.member(data, version)
    world.put_cache(unusable).chmod(0o620)
    world.put_cache(usable)
    _retain(world, new)
    assert world.cached() == sorted([_sha(new), _sha(usable)])
    world.subject(_image("unqualified subject"))
    assert _admit(world) == ("lkg", _sha(usable))


@pytest.mark.parametrize("flaw", ["foreign_owner", "over_bound"])
def test_ec_hold_10_other_files_the_reader_refuses_are_not_ranked(world, monkeypatch, flaw):
    flawed = _image("member 1.5.5", 8192 if flaw == "over_bound" else 4096)
    usable, new = _image("member 1.5.4"), _image("member 1.5.3")
    for data, version in ((flawed, "1.5.5"), (usable, "1.5.4"), (new, "1.5.3")):
        world.member(data, version)
    target = world.put_cache(flawed)
    world.put_cache(usable)
    if flaw == "foreign_owner":
        foreign = os.stat(target).st_ino
        real = agy_hold._readable_by_the_hold

        def as_if_foreign(info):
            if info.st_ino == foreign:
                info = os.stat_result(tuple(info[:4]) + (os.geteuid() + 4242,) + tuple(info[5:10]))
            return real(info)

        monkeypatch.setattr(agy_hold, "_readable_by_the_hold", as_if_foreign)
    else:
        monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", 6000)  # the 4096-byte images fit
    _retain(world, new)
    assert _sha(flawed) not in world.cached() and _sha(usable) in world.cached()


def test_ec_hold_10_retention_adds_nothing_when_the_cache_cannot_be_inspected(world, monkeypatch):
    """Finding 4: above ``MAX_DIR_ENTRIES`` the cache cannot be listed, so it cannot be
    pruned: the writer adds no new digest, and the bound holds."""
    monkeypatch.setattr(agy_hold, "MAX_DIR_ENTRIES", 4)
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    for index in range(5):
        world.put_cache(f"junk {index}".encode(), name=f"junk-{index}")
    before = world.cached()
    assert _admit(world) == ("subject", _sha(data))
    assert world.cached() == before and _sha(data) not in before
    monkeypatch.setattr(agy_hold, "MAX_DIR_ENTRIES", 1024)  # control: listable again
    _admit(world)
    assert _sha(data) in world.cached()


def test_ec_hold_10_clear_all_removes_nested_entries_completely(world, capsys):
    """Finding 2: nested content is removed through checked descriptors."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    nested = world.held() / "sub" / "deeper"
    nested.mkdir(parents=True)
    (nested / "entry").write_bytes(b"x")
    (world.held() / "sub" / "link").symlink_to(world.tmp / "outside-target")
    (world.tmp / "outside-target").write_bytes(b"outside")
    assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert "held_not_removed" not in printed and printed["held_removed"] == 5
    assert not world.held().exists()
    assert (world.tmp / "outside-target").read_bytes() == b"outside"


def test_ec_hold_10_clear_all_removes_a_held_symlink_without_traversing_it(world, capsys):
    """Finding 2: ``held`` itself a symlink: the link is removed, its target is untouched."""
    store = world.store()
    external = world.tmp / "external"
    external.mkdir()
    (external / ("a" * 64)).write_bytes(b"not ours")
    (store.host_dir / agy_hold.HELD_DIRNAME).symlink_to(external, target_is_directory=True)
    assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 0
    assert json.loads(capsys.readouterr().out)["held_removed"] == 1
    assert not os.path.lexists(store.host_dir / agy_hold.HELD_DIRNAME)
    assert (external / ("a" * 64)).read_bytes() == b"not ours"


def test_ec_hold_10_clear_all_reports_what_it_could_not_remove(world, capsys):
    """Finding 2: no silent leftovers. An entry that cannot be removed is named and the
    command fails."""
    if os.geteuid() == 0:
        pytest.skip("root removes from a mode-0500 directory")
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    stuck = world.held() / "stuck"
    stuck.mkdir()
    (stuck / "entry").write_bytes(b"x")
    stuck.chmod(0o500)
    try:
        assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 1
        captured = capsys.readouterr()
        printed = json.loads(captured.out)
        assert printed["held_not_removed"] == ["held/stuck/entry"]
        assert printed["held_removed"] == 1  # the image went; the stuck entry is reported
        assert "not removed completely" in captured.err
    finally:
        stuck.chmod(0o700)


def test_ec_hold_10_clear_all_reports_a_cache_it_cannot_reach_safely(world, capsys):
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    state = world.tmp / "state"
    state.chmod(0o775)
    try:
        assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 1
        assert json.loads(capsys.readouterr().out)["held_not_removed"] == ["held/"]
        assert world.held().exists()
    finally:
        state.chmod(0o755)


# ------------------------------------- round 4: the re-review's REQUIRED findings

def test_ec_hold_10_clear_all_removes_the_cache_of_a_store_missing_its_key(world, capsys):
    """Re-review 1: a store whose key is missing reads as absent, but its cache is still
    there and still removed (no silent leftover)."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    store = q.Store()
    (store.host_dir / "key").unlink()
    assert store.status() == "absent" and world.cached() == [_sha(data)]
    assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["held_removed"] == 1 and "held_not_removed" not in printed
    assert not world.held().exists()


def test_ec_hold_10_clear_all_reports_a_cache_whose_lock_is_refused(world, capsys):
    """Re-review 1: the lock is a symlink. The no-follow open refuses it, nothing is removed
    or followed, and the CLI reports the cache and fails, with no traceback."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    store = q.Store()
    outside = world.tmp / "outside-lock"
    outside.write_bytes(b"outside")
    lock = store.host_dir / "lock"
    if lock.exists():
        lock.unlink()
    lock.symlink_to(outside)
    assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["held_not_removed"] == ["held/"]
    assert world.cached() == [_sha(data)] and outside.read_bytes() == b"outside"


def test_ec_hold_10_clear_all_reports_a_cache_it_cannot_list(world, capsys):
    """Re-review 1: an enumeration failure is reported, not raised."""
    if os.geteuid() == 0:
        pytest.skip("root lists a mode-0300 directory")
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    world.held().chmod(0o300)
    try:
        assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 1
        assert json.loads(capsys.readouterr().out)["held_not_removed"] == ["held/"]
    finally:
        world.held().chmod(0o700)
    assert world.cached() == [_sha(data)]


def test_ec_hold_10_an_unreadable_regular_cache_file_is_removed(world):
    """Re-review 2: a digest-named regular file the reader cannot open (mode 000) is
    removed, inode-checked; a symlink beside it is still left alone."""
    unreadable, new = _image("member 1.5.4"), _image("member 1.5.3")
    world.member(unreadable, "1.5.4")
    world.member(new, "1.5.3")
    target = world.put_cache(unreadable)
    target.chmod(0o000)
    link = world.held() / ("e" * 64)
    link.symlink_to(world.tmp / "nowhere")
    _retain(world, new)
    assert not target.exists() and link.is_symlink()
    assert sorted(p.name for p in world.held().iterdir() if not p.is_symlink()) == [_sha(new)]


def test_ec_hold_10_a_prune_removal_that_fails_is_reported(world, monkeypatch, caplog):
    """Re-review 2: never left silently. A failed removal is logged with the file's name;
    the admission still returns."""
    victim, new = _image("member 1.5.4"), _image("member 1.5.3")
    world.member(victim, "1.5.4")
    world.member(new, "1.5.3")
    world.put_cache(victim).chmod(0o620)  # the reader would refuse it: it must go
    real = agy_hold._unlink_if_same

    def refuse(directory, name, identity):
        if name == _sha(victim):
            raise PermissionError(13, "synthetic refusal")
        return real(directory, name, identity)

    monkeypatch.setattr(agy_hold, "_unlink_if_same", refuse)
    with caplog.at_level("WARNING", logger="phase_loop_runtime.agy_hold"):
        _retain(world, new)
    assert any(f"held/{_sha(victim)}" in record.getMessage() for record in caplog.records)
    assert _sha(new) in world.cached()


@pytest.mark.parametrize("existing, added", [(3, True), (4, False), (5, False)])
def test_ec_hold_10_the_writer_never_takes_the_cache_past_the_readers_limit(world, monkeypatch, existing, added):
    """Re-review 3, the boundary exactly (MAX_DIR_ENTRIES = 4): with limit - 1 other names
    the image is added and the cache is still listable and usable; at the limit and above it
    nothing is added, and the reader can still list what it could before."""
    monkeypatch.setattr(agy_hold, "MAX_DIR_ENTRIES", 4)
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    for index in range(existing):
        world.put_cache(f"other {index}".encode(), name=f"other-{index}")
    _admit(world)
    names = world.cached()
    assert (_sha(data) in names) is added
    assert len(names) == existing + (1 if added else 0)
    anchor = agy_hold.open_anchor(world.held())
    try:
        listed = agy_hold._list_names(anchor)
    finally:
        os.close(anchor)
    assert (listed is None) is (existing > 4)
    if added:
        world.subject(_image("unqualified subject"))
        assert _admit(world) == ("lkg", _sha(data))  # the reader still reaches it


# ------------------------------------------- round 5: the r3 review's two reproductions

def test_ec_hold_10_clear_all_reports_a_cache_behind_an_inaccessible_ancestor(world, capsys):
    """r3 reproduction 1: a parent above the store root loses search permission. The cache
    may still be there, so it is reported, with exit status 1; never a silent exit 0."""
    if os.geteuid() == 0:
        pytest.skip("root ignores search permission")
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    state = world.tmp / "state"
    state.chmod(0o600)
    try:
        assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 1
        printed = json.loads(capsys.readouterr().out)
        assert printed["held_not_removed"] == ["held/"] and printed["held_removed"] == 0
    finally:
        state.chmod(0o755)
    assert world.cached() == [_sha(data)]  # it was there all along


def test_ec_hold_10_an_entry_removal_error_does_not_skip_the_cache_step(world, capsys):
    """r3 reproduction 2: a directory named like an entry (``failed-bad.json``) makes the
    entry removal raise. The cache step still runs and prints its result; the entry's error
    is then raised as clear has always raised it."""
    data = world.subject(_image("member 1.5.3"))
    world.member(data, "1.5.3")
    _admit(world)
    store = q.Store()
    (store.host_dir / "failed-bad.json").mkdir()
    assert store.status() == "ok"
    with pytest.raises(IsADirectoryError):
        q.cli_main(SimpleNamespace(action="clear", all=True))
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"removed": None, "held_removed": 1}
    assert not world.held().exists()
