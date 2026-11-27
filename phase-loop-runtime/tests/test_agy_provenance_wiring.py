"""The fetch ledger and the first-use call site (AGYROLL §1.2; PROVFWD-detail §1.3, §4.5).

Every case goes through the real ``requalify_once`` (the whole-board preflight) and a real
``Store`` in a temporary state home, with an in-memory upstream, an in-memory attestation
opener and an injected ledger clock. Nothing reaches the network or runs a model: help and
the three live operations are counting fakes.
"""
from __future__ import annotations

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tarfile
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

q = pytest.importorskip("phase_loop_runtime.agy_qualification")

from phase_loop_runtime import agy_attestation as att  # noqa: E402
from phase_loop_runtime import agy_hold  # noqa: E402
from phase_loop_runtime import agy_provenance as prov  # noqa: E402
from phase_loop_runtime import gemini_heartbeat as gh  # noqa: E402

MACHINE = "b" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
HELP = b"synthetic help\n"
DAY = prov.TOTAL_DOWNLOAD_WINDOW_S
CAP = prov.TOTAL_DOWNLOAD_CAP
START = 2_000_000_000.0


def _image(tag: str, size: int = 4096) -> bytes:
    head = f"#!/bin/sh\necho synthetic agy {tag}\n".encode()
    return head + b"#" * max(0, size - len(head))


def _archive(image: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(image)
        bundle.addfile(info, io.BytesIO(image))
    return buffer.getvalue()


def _versions(count):
    """``count`` stable versions, newest first."""
    return [f"1.{100 - i}.0" for i in range(count)]


class Upstream:
    """The paged release listing, attestation API and the archives, in memory; thread-safe; counts downloads."""

    def __init__(self, versions, *, broken=(), attestations=None):
        self.releases, self.blobs, self.downloads = [], {}, []
        self.attestations = attestations if attestations is not None else _Attestations()
        self.lock, self.break_mid_stream = threading.Lock(), set()
        for version in versions:
            archive = b"not a tarball: " + version.encode() if version in broken else _archive(_image(version))
            url = f"{prov.DOWNLOAD_PREFIX}{version}/{HOST.asset}"
            self.blobs[url] = archive
            self.releases.append({"tag_name": version, "draft": False, "prerelease": False, "assets": [
                {"name": HOST.asset, "browser_download_url": url, "digest": "sha256:" + sha256(archive).hexdigest()}]})

    def digest(self, version):
        return sha256(self.blobs[f"{prov.DOWNLOAD_PREFIX}{version}/{HOST.asset}"]).hexdigest()

    def open(self, url, *, accept):
        parts = urlsplit(url)
        if parts.hostname == prov.API_HOST:
            if "/attestations/" in parts.path:
                return self.attestations.open(url, accept=accept)
            query = parse_qs(parts.query)
            per_page, page = int(query["per_page"][0]), int(query.get("page", ["1"])[0])
            return io.BytesIO(json.dumps(self.releases[(page - 1) * per_page:page * per_page]).encode())
        version = url.rsplit("/", 2)[1]
        with self.lock:
            self.downloads.append(version)
        data = self.blobs[url]
        if version in self.break_mid_stream:
            return _Breaks(data)
        return io.BytesIO(data)


class _Breaks(io.BytesIO):
    def read(self, n=-1):
        if self.tell() > 16:
            raise ConnectionResetError("reset mid-download")
        return super().read(8)


class _Answer:
    def __init__(self, status, body):
        self.status, self._body = status, io.BytesIO(body)

    def read(self, n=-1):
        return self._body.read(n)

    def close(self):
        pass


class _Attestations:
    """``agy_attestation``'s opener: the attestations API only (first use never checks the
    second channel)."""

    def __init__(self):
        self.answer, self.requests = (404, b""), []

    def open(self, url, *, accept):
        self.requests.append(url)
        assert "/attestations/sha256:" in url, url
        return _Answer(*self.answer)


@pytest.fixture
def world(tmp_path, monkeypatch):
    previous = os.umask(0o022)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    monkeypatch.setattr(q, "_LAST_KNOWN_GOOD_PROVIDER", None)
    monkeypatch.setattr(q, "_HELP_MEMO", {})
    monkeypatch.setattr(q, "_REQUALIFIED", set())
    monkeypatch.setattr(agy_hold, "_WALK_ROOT", tmp_path)
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    monkeypatch.setattr(agy_hold, "VENDOR_STORES", (vendor,))
    members, qualified = [], {}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", qualified)
    monkeypatch.setattr(gh, "catalog_members", lambda path=None: [dict(item) for item in members])
    clock = [START]
    monkeypatch.setattr(q, "_ledger_clock", lambda: clock[0])
    attestations = _Attestations()
    monkeypatch.setattr(
        att,
        "_Opener",
        lambda **_: (_ for _ in ()).throw(AssertionError("agy_attestation._Opener must not bypass prov._Transport")),
    )
    upstream = Upstream(_versions(14), attestations=attestations)
    monkeypatch.setattr(prov, "_Transport", lambda: w.upstream)
    counts = SimpleNamespace(help=0, qualify=0)

    def fake_help(image, env, **_):
        counts.help += 1
        return HELP

    def fake_qualify(image, help_bytes, **_):
        counts.qualify += 1
        return {"status": "passed"}

    monkeypatch.setattr(q, "_run_help", fake_help)
    monkeypatch.setattr(q, "qualify_image", fake_qualify)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    home = tmp_path / "home"
    token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text("synthetic\n")
    w = SimpleNamespace(tmp=tmp_path, bindir=bindir, vendor=vendor, members=members, qualified=qualified,
                        clock=clock, attestations=attestations, upstream=upstream, counts=counts,
                        env={"PATH": str(bindir), "HOME": str(home)})

    def subject(data, *, version_dir=None):
        """The subject on PATH, or under ``opt/agy/<version_dir>/agy`` (a versioned path)."""
        if version_dir is None:
            path = bindir / "agy"
        else:
            path = tmp_path / "opt" / "agy" / version_dir / "agy"
            path.parent.mkdir(parents=True)
        path.write_bytes(data)
        path.chmod(0o755)
        return path

    w.subject = subject
    try:
        yield w
    finally:
        os.umask(previous)


def _preflight(world, path):
    """One whole-board preflight: ``("admitted", source)`` or ``(code, reason)``."""
    try:
        admission = q.requalify_once(world.env, subject_path=path)
    except ValueError as exc:
        assert type(exc) is ValueError, type(exc)  # the original refusal, unchanged
        return str(exc), getattr(exc, "reason", None)
    try:
        return "admitted", admission.source
    finally:
        admission.close()


def _key(world, path, profile=None):
    return (str(q.Store().host_dir), profile or q.agy_profile_digest(), sha256(Path(path).read_bytes()).hexdigest())


def _ledger(world, data):
    return q.Store().fetch_times(sha256(data).hexdigest(), HOST)


def _ledger_files(world):
    return sorted(q.Store().host_dir.glob("fetch_ledger-*.json"))


EXHAUSTED = (prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
CAPPED = (prov.UNVERIFIED, prov.DOWNLOAD_CAP_REACHED)


# ------------------------------------------------------------ 1-2: the hint and the walk

def test_a_versioned_subject_ninth_of_fourteen_is_admitted_in_one_preflight_and_one_fetch(world):
    """Case 1 (EC-PROVFWD-1). The hint reaches the resolver from the real call site."""
    versions = _versions(14)
    data = _image(versions[8])
    path = world.subject(data, version_dir=f"{versions[8]}-e363e1b1")
    world.upstream = Upstream(versions)
    assert _preflight(world, path) == ("admitted", "subject")
    assert world.upstream.downloads == [versions[8]]
    provenance = q.Store().get_provenance(sha256(data).hexdigest(), HOST, q.agy_profile_digest())
    assert provenance["release_version"] == versions[8]
    assert len(_ledger(world, data)) == 1


def test_an_unversioned_subject_is_reached_by_later_preflights_in_the_same_process(world):
    """Case 2 (EC-PROVFWD-2). A retryable refusal releases the once-per-key entry, so the
    next preflight runs first use again instead of a lookup. Mutation: not releasing it."""
    versions = _versions(14)
    data = _image(versions[8])
    path = world.subject(data)
    world.upstream = Upstream(versions)
    for call in range(4):
        assert _preflight(world, path) == EXHAUSTED
        assert _key(world, path) not in q._REQUALIFIED
        assert len(world.upstream.downloads) == 2 * (call + 1)
    assert _preflight(world, path) == ("admitted", "subject")
    assert world.upstream.downloads == versions[:9]
    assert _key(world, path) in q._REQUALIFIED  # an admission keeps the entry: later preflights look up
    assert world.counts.qualify == 1


# ------------------------------------------------------------------- 3: the daily cap

def test_a_tampered_image_gets_twelve_fetches_a_day_then_the_cap(world):
    """Case 3 (EC-PROVFWD-2). The count is on disk: every preflight uses a new Store. The cap
    is checked before the budget, so the preflight whose second fetch is the twelfth already
    reports the cap."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    for _ in range(CAP // prov.DOWNLOAD_BUDGET - 1):
        assert _preflight(world, path) == EXHAUSTED
    assert _preflight(world, path) == CAPPED
    assert len(world.upstream.downloads) == CAP
    assert _preflight(world, path) == CAPPED
    assert len(world.upstream.downloads) == CAP  # no further fetch
    assert len(_ledger(world, data)) == CAP  # read by a new Store object
    world.clock[0] += DAY + 1
    assert _preflight(world, path) == EXHAUSTED
    assert len(world.upstream.downloads) == CAP + prov.DOWNLOAD_BUDGET


def test_two_profiles_on_one_store_and_image_share_one_allowance(world, monkeypatch):
    """Case 3a. The ledger is keyed on the store and the image, not the profile.
    Mutation: keying the ledger with the profile digest (each profile gets twelve)."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    profile = ["a" * 64]
    monkeypatch.setattr(q, "agy_profile_digest", lambda: profile[0])
    for _ in range(3):
        assert _preflight(world, path) == EXHAUSTED
    profile[0] = "c" * 64
    for _ in range(2):
        assert _preflight(world, path) == EXHAUSTED
    assert _preflight(world, path) == CAPPED  # its second fetch was the twelfth
    assert len(world.upstream.downloads) == CAP
    assert _preflight(world, path) == CAPPED
    profile[0] = "a" * 64
    assert _preflight(world, path) == CAPPED
    assert len(world.upstream.downloads) == CAP


def test_a_pass_and_a_plain_clear_keep_the_count_and_clear_all_removes_it(world):
    """Case 3b. A pass resets transients, not the ledger; only ``clear --all`` removes it."""
    versions = _versions(14)
    data = _image(versions[2])
    path = world.subject(data)
    world.upstream = Upstream(versions)
    assert _preflight(world, path) == EXHAUSTED
    assert _preflight(world, path) == ("admitted", "subject")  # the pass ran reset_transients
    assert len(_ledger(world, data)) == 3
    assert q.cli_main(SimpleNamespace(action="clear", all=False)) == 0
    assert len(_ledger(world, data)) == 3
    assert q.cli_main(SimpleNamespace(action="clear", all=True)) == 0
    assert _ledger_files(world) == [] and _ledger(world, data) == ()


def test_two_profiles_racing_for_the_last_unit_fetch_once(world, monkeypatch):
    """Case 3c. Check and charge happen together under the store lock."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    store = q.Store()
    store.create()
    for _ in range(CAP - 1):
        store.note_fetch(sha256(data).hexdigest(), HOST, world.clock[0])
    profiles = {"first": "a" * 64, "second": "c" * 64}
    monkeypatch.setattr(q, "agy_profile_digest", lambda: profiles[threading.current_thread().name])
    barrier, outcomes = threading.Barrier(2), {}

    def run():
        barrier.wait()
        outcomes[threading.current_thread().name] = _preflight(world, path)

    threads = [threading.Thread(target=run, name=name) for name in profiles]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert len(world.upstream.downloads) == 1
    assert sorted(outcomes.values()) == [CAPPED, CAPPED]
    assert len(_ledger(world, data)) == CAP


# --------------------------------------------------------- 4-5: failures and the counts

def test_a_fetch_that_fails_mid_download_is_counted(world):
    """Case 4. ``note_fetch`` charges before the archive is opened."""
    versions = _versions(14)
    world.upstream = Upstream(versions)
    world.upstream.break_mid_stream.add(versions[0])
    data = _image("tampered")
    path = world.subject(data)
    assert _preflight(world, path) == (prov.UNAVAILABLE, None)
    assert world.upstream.downloads == [versions[0]] and len(_ledger(world, data)) == 1


def test_neither_retryable_reason_counts_a_transient_or_writes_a_failed_entry(world):
    """Case 5."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    outcomes = [_preflight(world, path) for _ in range(CAP // prov.DOWNLOAD_BUDGET + 2)]
    assert set(outcomes) == {EXHAUSTED, CAPPED}
    entries = q.Store().entries()
    assert "transient" not in entries and "failed" not in entries
    assert world.counts.help == world.counts.qualify == 0


# ------------------------------------------------------------- 6: a tampered ledger

def _tamper(path, how):
    if how == "payload":
        raw = json.loads(path.read_text())
        raw["payload"]["fetches"] = []
        path.write_text(json.dumps(raw))
    elif how == "garbage":
        path.write_text("not json")
    else:
        raw = json.loads(path.read_text())
        raw["mac"] = "0" * 64
        path.write_text(json.dumps(raw))


@pytest.mark.parametrize("how", ["payload", "garbage", "mac"])
def test_a_tampered_ledger_counts_as_full_for_a_day_and_is_never_read_as_empty(world, how):
    """Case 6. Absent and invalid are told apart (``Store.get`` reads both as None); the
    quarantine is persisted, authenticated, under the lock, and a new Store sees it."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    assert _preflight(world, path) == EXHAUSTED
    (ledger,) = _ledger_files(world)
    _tamper(ledger, how)
    seen_at = world.clock[0] = world.clock[0] + 3600
    assert _preflight(world, path) == CAPPED
    assert len(world.upstream.downloads) == prov.DOWNLOAD_BUDGET  # no fetch on a tampered ledger
    fresh = q.Store()
    payload = fresh.get("fetch_ledger", *([{"image_sha256": sha256(data).hexdigest(), "platform": HOST.name}] * 2))
    assert payload is not None and payload["quarantined_at"] == seen_at  # rewritten, authenticated
    assert len(fresh.fetch_times(sha256(data).hexdigest(), HOST)) == CAP
    world.clock[0] = seen_at + DAY - 1
    assert _preflight(world, path) == CAPPED  # still full just before the deadline
    world.clock[0] = seen_at + DAY + 1
    assert _preflight(world, path) == EXHAUSTED  # usable again 24 h after it was seen
    assert len(world.upstream.downloads) == 2 * prov.DOWNLOAD_BUDGET


def test_an_absent_ledger_is_empty(world):
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    assert _preflight(world, path) == EXHAUSTED
    for ledger in _ledger_files(world):
        ledger.unlink()
    assert _ledger(world, data) == ()
    assert _preflight(world, path) == EXHAUSTED
    assert len(world.upstream.downloads) == 2 * prov.DOWNLOAD_BUDGET


# ------------------------------------------------------------ 6a: the hinted exception

def test_the_hinted_candidate_keeps_first_place_after_one_rejection_and_goes_last_after_two(world):
    """Case 6a, through the real call site: the rejections are on disk."""
    versions = _versions(14)
    world.upstream = Upstream(versions, broken={versions[2]})
    data = _image(versions[5])
    path = world.subject(data, version_dir=f"{versions[2]}-0123abcd")  # the hint names the broken one
    assert _preflight(world, path) == EXHAUSTED
    assert world.upstream.downloads == [versions[2], versions[0]]
    assert _preflight(world, path) == EXHAUSTED
    assert world.upstream.downloads[2:] == [versions[2], versions[1]]
    assert _preflight(world, path) == EXHAUSTED
    assert world.upstream.downloads[4:] == [versions[3], versions[4]]  # the hint has gone last
    assert _preflight(world, path) == ("admitted", "subject")
    assert world.upstream.downloads[6:] == [versions[5]]
    rejected = q.Store().rejected_assets(sha256(data).hexdigest(), HOST, now=world.clock[0])
    assert rejected == {world.upstream.digest(versions[2]): 2}


# --------------------------------------------------------------- 7: with a held member

def test_a_retryable_refusal_admits_the_hold_and_still_releases_the_key(world):
    """Case 7. A hold stays eligible under ``provenance_unverified``; the once-per-key entry
    is released anyway, so the next preflight continues the walk."""
    member = _image("member 1.5.3")
    world.members.append({"release_version": "1.5.3", "image_sha256": sha256(member).hexdigest(),
                          "help_sha256": sha256(HELP).hexdigest()})
    world.qualified[sha256(member).hexdigest()] = sha256(HELP).hexdigest()
    held = world.vendor / f"1.5.3-{sha256(member).hexdigest()[:16]}"
    held.mkdir(mode=0o755)
    (held / "agy").write_bytes(member)
    (held / "agy").chmod(0o755)
    versions = _versions(14)
    world.upstream = Upstream(versions)
    data = _image(versions[8])
    path = world.subject(data)
    assert _preflight(world, path) == ("admitted", "lkg")
    assert _key(world, path) not in q._REQUALIFIED
    assert len(world.upstream.downloads) == prov.DOWNLOAD_BUDGET
    assert _preflight(world, path) == ("admitted", "lkg")  # first use ran again: two more fetches
    assert len(world.upstream.downloads) == 2 * prov.DOWNLOAD_BUDGET
    entries = q.Store().entries()
    assert "transient" not in entries and "failed" not in entries


# -------------------------------------------------------- 8: the two recorded statuses

def test_the_provenance_entry_carries_attestation_and_second_channel(world):
    """Case 8. First use records the attestation; the second channel is the catalog job's."""
    world.attestations.answer = (200, json.dumps({"attestations": [{"bundle": {}}]}).encode())
    versions = _versions(3)
    world.upstream = Upstream(versions, attestations=world.attestations)
    data = _image(versions[0])
    path = world.subject(data)
    assert _preflight(world, path) == ("admitted", "subject")
    provenance = q.Store().get_provenance(sha256(data).hexdigest(), HOST, q.agy_profile_digest())
    assert (provenance["attestation"], provenance["second_channel"]) == ("present_unverified", "not_checked")
    assert len(world.attestations.requests) == 1


def test_an_unavailable_attestation_refuses_first_use_without_a_provenance_entry(world):
    world.attestations.answer = (403, b'{"message": "API rate limit exceeded"}')
    versions = _versions(3)
    world.upstream = Upstream(versions, attestations=world.attestations)
    data = _image(versions[0])
    path = world.subject(data)
    assert _preflight(world, path) == (prov.UNAVAILABLE, None)
    assert q.Store().get_provenance(sha256(data).hexdigest(), HOST, q.agy_profile_digest()) is None


# ------------------------------------------------------------- the store and its key

def test_the_ledger_is_keyed_on_image_and_platform_only_and_leaves_the_store_ok(world):
    store = q.Store()
    store.create()
    digest = sha256(b"x").hexdigest()
    store.note_fetch(digest, HOST, START)
    store.note_rejected(digest, HOST, "d" * 64, START)
    assert store.status() == "ok" and "fetch_ledger" in store.entries()
    assert store.fetch_times(digest, HOST) == (START,)
    assert store.rejected_assets(digest, HOST, now=START) == {"d" * 64: 1}
    (ledger,) = _ledger_files(world)
    assert ledger == store._path("fetch_ledger", {"image_sha256": digest, "platform": HOST.name})
    assert "fetch_ledger" in q._ENTRY_TYPES


def test_the_ledger_drops_what_is_older_than_a_day_on_the_next_write(world):
    store = q.Store()
    store.create()
    digest = sha256(b"x").hexdigest()
    for i in range(CAP):
        store.note_fetch(digest, HOST, START + i)
    with pytest.raises(prov.ProvenanceError) as exc:  # the charge itself enforces the cap
        store.note_fetch(digest, HOST, START + CAP)
    assert exc.value.reason == prov.DOWNLOAD_CAP_REACHED
    assert len(store.fetch_times(digest, HOST)) == CAP
    store.note_fetch(digest, HOST, START + DAY + 100)
    assert store.fetch_times(digest, HOST) == (START + DAY + 100,)


def test_a_provenance_refusal_keeps_its_code_and_reason_and_stays_a_plain_value_error():
    """The hold handler re-raises the original refusal unchanged, so its type stays ValueError."""
    exc = q.provenance_refusal(prov.ProvenanceError(prov.UNVERIFIED, prov.BUDGET_EXHAUSTED))
    assert type(exc) is ValueError and str(exc) == prov.UNVERIFIED and exc.reason == prov.BUDGET_EXHAUSTED
    assert q.provenance_refusal(prov.ProvenanceError(prov.UNAVAILABLE)).reason is None
    assert q.RETRYABLE_PROVENANCE_REASONS == {prov.BUDGET_EXHAUSTED, prov.DOWNLOAD_CAP_REACHED}


# ------------------------------------------- review fixes: the charge and the decoder

def _ledger_payload(store, data):
    context = {"image_sha256": sha256(data).hexdigest(), "platform": HOST.name}
    return store.get("fetch_ledger", context, context)


def test_a_failed_charge_time_read_refuses_with_no_fetch_and_persists_the_quarantine(world, monkeypatch):
    """Review fix 1. The check read shows room; the charge's own read fails once. The charge
    quarantines the ledger and refuses the retryable cap, so no archive is requested, and the
    quarantine is not overwritten. Mutation: charging on top of a just-written quarantine."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    charging, failed = [False], [False]
    real_note, real_read = q.Store.note_fetch, q.Store._read

    def note_fetch(self, *args, **kwargs):
        charging[0] = True
        try:
            return real_note(self, *args, **kwargs)
        finally:
            charging[0] = False

    def read(self, target):
        if charging[0] and not failed[0] and target.name.startswith("fetch_ledger-"):
            failed[0] = True
            raise OSError("injected charge-time read failure")
        return real_read(self, target)

    monkeypatch.setattr(q.Store, "note_fetch", note_fetch)
    monkeypatch.setattr(q.Store, "_read", read)
    assert _preflight(world, path) == CAPPED
    assert failed[0] and world.upstream.downloads == []
    payload = _ledger_payload(q.Store(), data)  # a fresh Store sees the persisted quarantine
    assert payload["quarantined_at"] == world.clock[0] and payload["fetches"] == [world.clock[0]] * CAP
    assert _preflight(world, path) == CAPPED and world.upstream.downloads == []


def test_a_charge_that_finds_the_ledger_full_refuses_and_writes_nothing(world, monkeypatch):
    """The check and the charge read separately; the charge decides. Here the check read is
    made to show room while the ledger on disk is full."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    store = q.Store()
    store.create()
    for i in range(CAP):
        store.note_fetch(sha256(data).hexdigest(), HOST, world.clock[0] - i)
    before = _ledger_files(world)[0].read_bytes()
    monkeypatch.setattr(q.Store, "fetch_times", lambda self, image_sha256, host: ())
    assert _preflight(world, path) == CAPPED
    assert world.upstream.downloads == [] and _ledger_files(world)[0].read_bytes() == before


def test_a_deeply_nested_ledger_is_quarantined_not_raised(world):
    """Review fix 2. A 40,000-byte nested array makes the JSON decoder recurse past its limit;
    that is invalid ledger data: the authenticated quarantine and the retryable refusal."""
    world.upstream = Upstream(_versions(30))
    data = _image("tampered")
    path = world.subject(data)
    assert _preflight(world, path) == EXHAUSTED
    (ledger,) = _ledger_files(world)
    ledger.write_text("[" * 20_000 + "]" * 20_000)
    assert ledger.stat().st_size == 40_000 and oct(ledger.stat().st_mode & 0o777) == "0o600"
    world.clock[0] += 3600
    assert _preflight(world, path) == CAPPED
    assert len(world.upstream.downloads) == prov.DOWNLOAD_BUDGET  # no fetch after it
    payload = _ledger_payload(q.Store(), data)
    assert payload["quarantined_at"] == world.clock[0] and len(payload["fetches"]) == CAP


def test_a_quarantine_marker_survives_later_writes_until_it_expires(world):
    store = q.Store()
    store.create()
    digest = sha256(b"x").hexdigest()
    store.note_fetch(digest, HOST, START)
    path = store._path("fetch_ledger", {"image_sha256": digest, "platform": HOST.name})
    path.write_text("not json")
    assert len(store.fetch_times(digest, HOST)) == CAP  # quarantined at START
    store.note_rejected(digest, HOST, "d" * 64, START + 10)
    payload = _ledger_payload(store, b"x")
    assert payload["quarantined_at"] == START and len(payload["fetches"]) == CAP
    with pytest.raises(prov.ProvenanceError) as exc:
        store.note_fetch(digest, HOST, START + 20)
    assert exc.value.reason == prov.DOWNLOAD_CAP_REACHED
    store.note_fetch(digest, HOST, START + DAY + 1)  # the quarantine has expired
    payload = _ledger_payload(store, b"x")
    assert "quarantined_at" not in payload and payload["fetches"] == [START + DAY + 1]
