"""Forward provenance for any stable release (AGYROLL §1.2; PROVFWD-detail §1, §4.1).

The resolver examines every listed stable release, newest first after the hint, within a
per-call download budget and a rolling daily cap. Nothing here reaches the network: the
paged listing and the archives are served from memory, the ledger and the member cache are
plain callables, and the clock is injected.
"""
from __future__ import annotations

import builtins
import inspect
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.parse import parse_qs, urlsplit

import pytest

from phase_loop_runtime import agy_provenance as prov

HOST = prov.HostPlatform("linux", "x64", "glibc")
DAY = prov.TOTAL_DOWNLOAD_WINDOW_S


def _archive(image: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(image)
        bundle.addfile(info, io.BytesIO(image))
    return buffer.getvalue()


def _image(version: str) -> bytes:
    return f"#!/bin/sh\necho synthetic agy {version}\n".encode()


class Upstream:
    """The paged release listing (API order, newest first) and the archive downloads."""

    def __init__(self, versions=(), *, broken=()):
        self.releases, self.blobs, self.listings, self.downloads = [], {}, [], []
        for version in versions:
            self.add(version, archive=b"not a tarball: " + version.encode() if version in broken else None)

    def add(self, version, *, archive=None, prerelease=False, draft=False):
        """Append ``version`` as the next OLDER release."""
        archive = archive if archive is not None else _archive(_image(version))
        url = f"{prov.DOWNLOAD_PREFIX}{version}/{HOST.asset}"
        self.blobs[url] = archive
        self.releases.append({"tag_name": version, "prerelease": prerelease, "draft": draft,
                              "assets": [{"name": HOST.asset, "browser_download_url": url,
                                          "digest": "sha256:" + sha256(archive).hexdigest()}]})

    def open(self, url, *, accept):
        parts = urlsplit(url)
        if parts.hostname == prov.API_HOST:
            assert parts.path == f"/repos/{prov.REPO}/releases", url
            query = parse_qs(parts.query)
            per_page, page = int(query["per_page"][0]), int(query.get("page", ["1"])[0])
            self.listings.append(page)
            return io.BytesIO(json.dumps(self.releases[(page - 1) * per_page:page * per_page]).encode())
        self.downloads.append(url.rsplit("/", 2)[1])
        return io.BytesIO(self.blobs[url])


class Ledger:
    """The fetch ledger and member cache a store would keep, in memory."""

    def __init__(self, clock=1_000_000.0):
        self.clock, self.fetches, self.rejected_at, self.members = clock, [], {}, {}

    def now(self):
        return self.clock

    def kwargs(self, **extra):
        return {"cached_member": lambda asset: self.members.get(asset.digest),
                "remember_member": lambda asset, member: self.members.__setitem__(asset.digest, member),
                "fetch_times": lambda: tuple(self.fetches),
                "note_fetch": self.fetches.append,
                "rejected": lambda: {digest: sum(1 for at in times if at > self.clock - DAY)
                                     for digest, times in self.rejected_at.items()},
                "note_rejected": lambda digest, at: self.rejected_at.setdefault(digest, []).append(at),
                "attest": lambda asset: "absent", "now": self.now, **extra}


def _versions(count, start=100):
    """``count`` distinct versions, newest first."""
    return [f"1.{start - i}.0" for i in range(count)]


def _find(upstream, ledger, version, **kwargs):
    return prov.find_provenance(sha256(_image(version)).hexdigest(), host=HOST, transport=upstream,
                                **ledger.kwargs(**kwargs))


def _refusal(fn):
    with pytest.raises(prov.ProvenanceError) as exc:
        fn()
    return str(exc.value), exc.value.reason


# ------------------------------------------------------------------ 1-2: any position

def test_a_subject_behind_eighteen_newer_releases_is_found_by_repeated_calls():
    """Case 1. Mutation: restoring a slice of the listing (the window). Calls are six hours
    apart, so the daily cap (case 4) is not what paces them."""
    versions = _versions(19)
    upstream, ledger = Upstream(versions), Ledger()
    calls = 0
    while True:
        calls += 1
        ledger.clock += 6 * 3600
        before = len(upstream.downloads)
        try:
            found = _find(upstream, ledger, versions[-1])
            break
        except prov.ProvenanceError as exc:
            assert (str(exc), exc.reason) == (prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
        finally:
            assert len(upstream.downloads) - before <= prov.DOWNLOAD_BUDGET
        assert calls < 19
    assert found.asset.version == versions[-1] and calls == 10
    assert len(upstream.downloads) == 19 == len(set(upstream.downloads))


def test_with_the_hint_the_same_subject_is_found_in_one_call_and_one_fetch():
    versions = _versions(19)
    upstream, ledger = Upstream(versions), Ledger()
    found = _find(upstream, ledger, versions[-1], hint=versions[-1])
    assert found.asset.version == versions[-1] and upstream.downloads == [versions[-1]]


def test_a_subject_ninth_of_fourteen_gets_a_provenance():
    """Case 2."""
    versions = _versions(14)
    upstream, ledger = Upstream(versions), Ledger()
    results = []
    for _ in range(5):
        try:
            results.append(_find(upstream, ledger, versions[8]))
            break
        except prov.ProvenanceError as exc:
            results.append(exc.reason)
    assert results[:-1] == [prov.BUDGET_EXHAUSTED] * 4
    assert isinstance(results[-1], prov.Provenance) and results[-1].asset.version == versions[8]
    assert results[-1].platform == HOST.name and results[-1].image_sha256 == sha256(_image(versions[8])).hexdigest()


# ----------------------------------------------------------------- 3-4: the two bounds

def test_a_tampered_image_costs_the_budget_per_call_and_progresses_through_the_cache():
    """Case 3. Mutations: no per-call budget; re-fetching a cached member."""
    versions = _versions(5)
    upstream, ledger = Upstream(versions), Ledger()
    tampered = "0" * 64

    def find():
        return prov.find_provenance(tampered, host=HOST, transport=upstream, budget=2, **ledger.kwargs())

    assert _refusal(find) == (prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
    assert upstream.downloads == versions[:2]
    assert _refusal(find) == (prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
    assert upstream.downloads == versions[:4]
    assert _refusal(find) == (prov.UNVERIFIED, None)  # the last one fits, nothing is left
    assert upstream.downloads == versions
    assert _refusal(find) == (prov.UNVERIFIED, None)  # every member cached: definitive, no fetch
    assert upstream.downloads == versions


def test_twelve_fetches_in_a_day_reach_the_cap_with_zero_fetches():
    """Case 4. Mutation: no total bound, or checking it after the fetch."""
    upstream, ledger = Upstream(_versions(3)), Ledger()
    ledger.fetches = [ledger.clock - 60 * i for i in range(prov.TOTAL_DOWNLOAD_CAP)]
    assert _refusal(lambda: _find(upstream, ledger, "1.98.0")) == (prov.UNVERIFIED, prov.DOWNLOAD_CAP_REACHED)
    assert upstream.downloads == [] and len(ledger.fetches) == prov.TOTAL_DOWNLOAD_CAP


def test_fetch_times_older_than_a_day_do_not_count():
    upstream, ledger = Upstream(_versions(3)), Ledger()
    ledger.fetches = [ledger.clock - DAY - 1] * 50 + [ledger.clock - DAY]  # at or before the window start
    assert _find(upstream, ledger, "1.99.0").asset.version == "1.99.0"


def test_the_cap_is_checked_before_every_fetch_including_within_one_call():
    upstream, ledger = Upstream(_versions(3)), Ledger()
    ledger.fetches = [ledger.clock] * (prov.TOTAL_DOWNLOAD_CAP - 1)
    assert _refusal(lambda: _find(upstream, ledger, "1.98.0")) == (prov.UNVERIFIED, prov.DOWNLOAD_CAP_REACHED)
    assert upstream.downloads == ["1.100.0"]


def test_note_fetch_is_called_once_per_fetch_and_before_it():
    upstream, ledger = Upstream(_versions(3)), Ledger()
    order = []
    real_open = upstream.open

    def open_(url, *, accept):
        order.append(("open", url.rsplit("/", 2)[1] if "/download/" in url else "listing"))
        return real_open(url, accept=accept)

    upstream.open = open_
    found = _find(upstream, ledger, "1.99.0", note_fetch=lambda at: order.append(("note", at)) or ledger.fetches.append(at))
    assert found.asset.version == "1.99.0"
    assert order == [("open", "listing"), ("note", ledger.clock), ("open", "1.100.0"),
                     ("note", ledger.clock), ("open", "1.99.0")]


class _BreaksMidStream(io.BytesIO):
    def read(self, n=-1):
        if self.tell() > 16:
            raise ConnectionResetError("reset mid-download")
        return super().read(min(n, 8) if n and n > 0 else 8)


@pytest.mark.parametrize("failure", ["open", "mid_stream"])
def test_a_fetch_that_fails_is_still_counted(failure):
    """A download that fails or is interrupted has spent its unit: it was noted before it began."""
    upstream, ledger = Upstream(_versions(2)), Ledger()
    real_open = upstream.open

    def open_(url, *, accept):
        if "/download/" not in url:
            return real_open(url, accept=accept)
        if failure == "open":
            raise prov.ProvenanceError(prov.UNAVAILABLE)
        return _BreaksMidStream(real_open(url, accept=accept).read())

    upstream.open = open_
    assert _refusal(lambda: _find(upstream, ledger, "1.99.0")) == (prov.UNAVAILABLE, None)
    assert len(ledger.fetches) == 1


# ------------------------------------------------------------------------ 5-6: the hint

@pytest.mark.parametrize("path,hint", [
    ("opt/consiliency/operational-clis/agy/1.5.3-e363e1b1c0ffee/agy", "1.5.3"),
    ("opt/agy/1.5.13/bin/agy", "1.5.13"),
    ("opt/agy/1.5.13+build.7/agy", "1.5.13"),
    ("opt/agy/2.0.0/1.5.3/agy", "2.0.0"),
    ("usr/local/bin/agy", None),
    ("opt/agy/v1.5.3/agy", None),
    ("opt/agy/1.5/agy", None),
    ("opt/agy/1.5.3_x/agy", None),
    ("opt/agy/１.5.3/agy", None),
])
def test_version_hint_reads_the_first_matching_path_component(tmp_path, path, hint):
    """The contract's example and its edges, under a root that does not exist (so no host
    symlink resolves them elsewhere)."""
    assert prov.version_hint(tmp_path / "absent-root" / path) == hint


def test_version_hint_resolves_a_symlinked_path_first(tmp_path):
    target = tmp_path / "store" / "1.5.13-abcdef" / "agy"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    link = tmp_path / "bin" / "agy"
    link.parent.mkdir()
    link.symlink_to(target)
    assert prov.version_hint(link) == "1.5.13"
    assert prov.version_hint(str(link)) == "1.5.13"


def test_version_hint_opens_and_executes_nothing(monkeypatch, tmp_path):
    """Mutation: reading ``--version`` or the image's bytes for the hint."""
    target = tmp_path / "1.5.13" / "agy"
    target.parent.mkdir()
    target.write_bytes(b"#!/bin/sh\necho 9.9.9\n")

    calls = []

    def refuse(*_a, **_k):
        calls.append(_a)
        raise AssertionError("version_hint opened or executed something")

    with monkeypatch.context() as patched:  # undone before any fixture teardown opens files
        patched.setattr(builtins, "open", refuse)
        patched.setattr(io, "open", refuse)
        patched.setattr(os, "open", refuse)
        for name in ("run", "Popen", "check_output", "call", "check_call"):
            patched.setattr(subprocess, name, refuse)
        hints = (prov.version_hint(target), prov.version_hint(tmp_path / "missing" / "agy"))
    assert hints == ("1.5.13", None) and calls == []


def test_a_wrong_hint_still_admits_the_genuine_image():
    """Case 6. The hint only orders; admission is the member digest."""
    versions = _versions(3)
    upstream, ledger = Upstream(versions), Ledger()
    assert _refusal(lambda: _find(upstream, ledger, versions[1], hint=versions[2])) == (
        prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
    assert upstream.downloads == [versions[2], versions[0]]
    found = _find(upstream, ledger, versions[1], hint=versions[2])
    assert found.asset.version == versions[1]
    assert upstream.downloads == [versions[2], versions[0], versions[1]]


def test_a_hint_never_admits_a_non_matching_image():
    versions = _versions(3)
    upstream, ledger = Upstream(versions), Ledger()
    assert _refusal(lambda: prov.find_provenance("0" * 64, host=HOST, transport=upstream, hint=versions[0],
                                                 budget=10, **ledger.kwargs())) == (prov.UNVERIFIED, None)


def test_a_hint_that_names_no_listed_release_is_ignored():
    versions = _versions(3)
    upstream, ledger = Upstream(versions), Ledger()
    found = _find(upstream, ledger, versions[0], hint="7.7.7")
    assert found.asset.version == versions[0] and upstream.downloads == [versions[0]]


def test_a_hint_that_names_a_prerelease_is_ignored():
    upstream, ledger = Upstream(["1.3.0"]), Ledger()
    upstream.add("1.2.0", prerelease=True)
    upstream.add("1.1.0")
    found = _find(upstream, ledger, "1.3.0", hint="1.2.0")
    assert found.asset.version == "1.3.0" and upstream.downloads == ["1.3.0"]


# ---------------------------------------------------------------------- 7: the listing

def test_a_second_page_is_requested_only_when_needed():
    versions = _versions(150, start=200)
    upstream, ledger = Upstream(versions), Ledger()
    assert _find(upstream, ledger, versions[0]).asset.version == versions[0]
    assert upstream.listings == [1]
    for version in versions[:100]:
        ledger.members[sha256(upstream.blobs[f"{prov.DOWNLOAD_PREFIX}{version}/{HOST.asset}"]).hexdigest()] = "0" * 64
    upstream.listings.clear()
    assert _find(upstream, ledger, versions[100]).asset.version == versions[100]
    assert upstream.listings == [1, 2]


def test_limit_one_makes_one_request():
    upstream = Upstream(_versions(150, start=200))
    (newest,) = prov.stable_releases(upstream, limit=1)
    assert newest["tag_name"] == "1.200.0" and upstream.listings == [1]


def test_a_listing_longer_than_max_listed_stops_there():
    upstream = Upstream(_versions(prov.MAX_LISTED + 50, start=500))
    releases = prov.stable_releases(upstream)
    assert len(releases) == prov.MAX_LISTED and upstream.listings == [1, 2, 3]
    assert prov.MAX_LISTED == 300 and prov.LISTING_PAGE == 100


def test_a_two_page_listing_keeps_api_order_and_the_stable_filter():
    upstream = Upstream()
    for i in range(130):
        upstream.add(f"1.{300 - i}.0", prerelease=(i % 10 == 3), draft=(i % 10 == 7))
    releases = prov.stable_releases(upstream)
    tags = [r["tag_name"] for r in releases]
    assert tags == [r["tag_name"] for r in upstream.releases if not r["prerelease"] and not r["draft"]]
    assert upstream.listings == [1, 2]


def test_each_page_keeps_the_listing_byte_bound(monkeypatch):
    upstream = Upstream(_versions(5))
    monkeypatch.setattr(prov, "MAX_LISTING_BYTES", 64)
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        prov.stable_releases(upstream)


def test_a_short_page_ends_the_listing():
    upstream = Upstream(_versions(100))
    prov.stable_releases(upstream)
    assert upstream.listings == [1, 2]  # a full first page asks for a second, which is empty


# ----------------------------------------------------------- 8: rejected assets go last

def test_rejected_archives_are_tried_last_on_the_next_call():
    """Case 8. Two malformed archives head the listing: the first call spends its budget on
    them; the next call reaches the untried releases first."""
    versions = _versions(4)
    upstream, ledger = Upstream(versions, broken=versions[:2]), Ledger()
    assert _refusal(lambda: _find(upstream, ledger, versions[3])) == (prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
    assert upstream.downloads == versions[:2] and len(ledger.rejected_at) == 2
    found = _find(upstream, ledger, versions[3])
    assert found.asset.version == versions[3] and upstream.downloads == versions[:2] + versions[2:4]


def test_a_rejected_archive_is_still_tried_after_every_untried_one():
    versions = _versions(3)
    upstream, ledger = Upstream(versions, broken=versions[:1]), Ledger()
    ledger.rejected_at[sha256(upstream.blobs[f"{prov.DOWNLOAD_PREFIX}{versions[0]}/{HOST.asset}"]).hexdigest()] = [
        ledger.clock]
    for v in versions[1:]:
        ledger.members[sha256(upstream.blobs[f"{prov.DOWNLOAD_PREFIX}{v}/{HOST.asset}"]).hexdigest()] = "0" * 64
    assert _refusal(lambda: _find(upstream, ledger, "9.9.9")) == (prov.UNVERIFIED, None)
    assert upstream.downloads == [versions[0]]  # still examined, last, and it still costs a fetch
    assert len(ledger.fetches) == 1


def _digest(upstream, version):
    return sha256(upstream.blobs[f"{prov.DOWNLOAD_PREFIX}{version}/{HOST.asset}"]).hexdigest()


def test_the_hinted_candidate_keeps_first_place_after_one_rejection_and_goes_last_after_two():
    """The exception to rejected-last: one rejection may be a download damaged in transit."""
    versions = _versions(4)
    upstream, ledger = Upstream(versions), Ledger()
    ledger.rejected_at[_digest(upstream, versions[1])] = [ledger.clock]
    assert _find(upstream, ledger, versions[1], hint=versions[1]).asset.version == versions[1]
    assert upstream.downloads == [versions[1]]
    upstream.downloads.clear()
    ledger.members.clear()
    ledger.rejected_at[_digest(upstream, versions[1])] = [ledger.clock, ledger.clock]
    ledger.rejected_at[_digest(upstream, versions[2])] = [ledger.clock]
    found = _find(upstream, ledger, versions[1], hint=versions[1], budget=4)
    assert found.asset.version == versions[1]
    # untried in listing order, then the other rejected one, then the twice-rejected hint
    assert upstream.downloads == [versions[0], versions[3], versions[2], versions[1]]


def test_old_rejections_no_longer_defer():
    versions = _versions(2)
    upstream, ledger = Upstream(versions), Ledger()
    ledger.rejected_at[sha256(upstream.blobs[f"{prov.DOWNLOAD_PREFIX}{versions[0]}/{HOST.asset}"]).hexdigest()] = [
        ledger.clock - DAY - 1]
    assert _find(upstream, ledger, versions[0]).asset.version == versions[0]
    assert upstream.downloads == [versions[0]]


# -------------------------------------------------------- 9-10: attestation and the code

def test_the_match_records_the_attest_value_once_and_never_the_second_channel():
    """Case 9."""
    upstream, ledger = Upstream(_versions(2)), Ledger()
    seen = []
    found = _find(upstream, ledger, "1.99.0", attest=lambda asset: seen.append(asset) or "present_unverified")
    assert found.attestation == "present_unverified" and found.second_channel == "not_checked"
    assert [asset.version for asset in seen] == ["1.99.0"]
    bare = prov.Provenance("a" * 64, HOST.name, found.asset)
    assert (bare.attestation, bare.second_channel) == ("not_checked", "not_checked")


def test_an_unavailable_attestation_refuses():
    upstream, ledger = Upstream(_versions(2)), Ledger()

    def attest(asset):
        raise prov.ProvenanceError(prov.UNAVAILABLE)

    assert _refusal(lambda: _find(upstream, ledger, "1.99.0", attest=attest)) == (prov.UNAVAILABLE, None)


def test_the_default_attest_is_the_attestation_query(monkeypatch):
    from phase_loop_runtime import agy_attestation
    seen = []
    monkeypatch.setattr(agy_attestation, "attestation_status", lambda asset, transport=None: seen.append(asset) or "absent")
    upstream, ledger = Upstream(_versions(1)), Ledger()
    kwargs = ledger.kwargs()
    del kwargs["attest"]
    found = prov.find_provenance(sha256(_image("1.100.0")).hexdigest(), host=HOST, transport=upstream, **kwargs)
    assert found.attestation == "absent" and len(seen) == 1


def test_a_provenance_error_keeps_its_code_as_its_string():
    """Case 10."""
    exc = prov.ProvenanceError(prov.UNVERIFIED, prov.BUDGET_EXHAUSTED)
    assert str(exc) == prov.UNVERIFIED and exc.reason == prov.BUDGET_EXHAUSTED
    assert str(prov.ProvenanceError(prov.UNAVAILABLE)) == prov.UNAVAILABLE
    assert prov.ProvenanceError(prov.UNAVAILABLE).reason is None
    assert isinstance(exc, ValueError)
    assert (prov.DOWNLOAD_BUDGET, prov.TOTAL_DOWNLOAD_CAP, prov.TOTAL_DOWNLOAD_WINDOW_S) == (2, 12, 86_400)
    assert (prov.BUDGET_EXHAUSTED, prov.DOWNLOAD_CAP_REACHED) == ("budget_exhausted", "download_cap_reached")


# ------------------------------------------------------------------- 11: no window left

def test_no_recency_window_remains_in_any_agy_module():
    """Case 11 (EC-PROVFWD-6). Mutation: keeping ``RECENCY_WINDOW`` or a ``window=`` argument."""
    package = Path(prov.__file__).resolve().parent
    sources = sorted(package.glob("agy_*.py"))
    assert {path.name for path in sources} >= {"agy_provenance.py", "agy_watch.py", "agy_attestation.py"}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "RECENCY_WINDOW" not in text, path.name
        assert re.search(r"\bwindow\s*=", text) is None, path.name
    assert not hasattr(prov, "RECENCY_WINDOW")
    assert "per_page=30" not in prov.RELEASES_PATH
    assert "window" not in inspect.signature(prov.find_provenance).parameters
    assert "window" not in inspect.signature(prov.stable_releases).parameters
