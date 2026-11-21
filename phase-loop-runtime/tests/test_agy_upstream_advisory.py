"""`verify_qualified_agy_image.py --upstream-only`: membership is advisory (agent-harness#1333 PR1).

A newer upstream agy release that is not a shipped member only warns; hosts self-qualify it
on first use. The newest SHIPPED member's vendor asset digest, URL and archive stay blocking,
so the scheduled `upstream` job reds on any member-integrity failure and never on membership.

The newest upstream release is the first stable entry of the first listing page, chosen with
the resolver's stable filter (PROVFWD-detail §3.2), not ``/releases/latest``.

Nothing here reaches the network: the release API and the asset are served in memory, and
the catalog is replaced by synthetic records whose digests match a synthetic archive.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import re
import tarfile
from urllib.parse import parse_qs, urlsplit

from types import SimpleNamespace

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
REPO = Path(__file__).resolve().parents[2]
QUALIFIED = REPO / ".github" / "workflows" / "qualified-agy-image.yml"
RELEASES = "https://api.github.com/repos/google-antigravity/antigravity-cli/releases"
LISTING = f"{RELEASES}?per_page=100"
PUBLISHED = "2026-11-19T08:38:26Z"
DOWNLOAD = "https://github.com/google-antigravity/antigravity-cli/releases/download/"
ASSET = "agy_cli_linux_x64.tar.gz"
WARNING = "::warning::newest upstream agy {} is not a shipped member; hosts self-qualify it on first use"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or not QUALIFIED.is_file(),
    reason="the verifier and its workflow are repository source, absent from the standalone layout",
)


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(executable):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(executable)
        bundle.addfile(info, io.BytesIO(executable))
    return buffer.getvalue()


class Upstream:
    """The release listing, by-tag lookups and asset downloads; records every URL.

    The listing is ``ahead`` (entries the stable filter must skip), then ``latest``, then the
    other releases."""

    def __init__(self):
        self.releases, self.blobs, self.calls = {}, {}, []
        self.latest, self.ahead = None, []

    def add(self, version, archive, *, digest=None, url=None):
        url = url or f"{DOWNLOAD}{version}/{ASSET}"
        self.blobs[url] = archive
        self.releases[version] = {"tag_name": version, "draft": False, "prerelease": False,
                                  "published_at": PUBLISHED, "assets": [
                                      {"name": ASSET, "browser_download_url": url,
                                       "digest": digest or "sha256:" + sha256(archive).hexdigest()}]}

    def listing(self):
        rest = [release for tag, release in self.releases.items() if tag != self.latest]
        return self.ahead + [self.releases[self.latest]] + rest

    def urlopen(self, request, timeout=None):
        url = getattr(request, "full_url", request)
        self.calls.append(url)
        assert url != f"{RELEASES}/latest", "the newest release comes from the listing"
        if url == LISTING:
            return io.BytesIO(json.dumps(self.listing()).encode())
        if url.startswith(f"{RELEASES}/tags/"):
            return io.BytesIO(json.dumps(self.releases[url.rsplit("/", 1)[1]]).encode())
        return io.BytesIO(self.blobs[url])


@pytest.fixture
def world(verifier, monkeypatch, tmp_path):
    """Three shipped members out of version order, each with a matching synthetic asset.

    Catalog order (and string order) would pick 1.9.0; the newest member is 1.10.0.
    """
    upstream = Upstream()
    records, archives = [], {}
    for version in ("1.0.0", "1.10.0", "1.9.0"):
        executable = f"#!/bin/sh\necho synthetic agy {version}\n".encode()
        archive = _archive(executable)
        archives[version] = tmp_path / f"{version}.tar.gz"
        archives[version].write_bytes(archive)
        upstream.add(version, archive)
        records.append({"release_version": version, "upstream_asset_sha256": sha256(archive).hexdigest(),
                        "image_sha256": sha256(executable).hexdigest(), "source_sha256": {"x.py": "0" * 64}})
    upstream.add("2.0.0", _archive(b"#!/bin/sh\necho not a member\n"))
    upstream.latest = "2.0.0"
    monkeypatch.setattr(verifier, "contract", lambda: records)
    monkeypatch.setattr(verifier, "urlopen", upstream.urlopen)  # asset downloads
    # Releases API reads go through their own redirect-confined opener (agent-harness#1993).
    monkeypatch.setattr(verifier, "_api_opener", lambda *handlers: SimpleNamespace(open=upstream.urlopen))

    def run(*extra):
        # The mode's own function, so a refusal surfaces as its ValueError (main() turns it
        # into exit status 1, tested below).
        archive = Path(extra[extra.index("--archive") + 1]) if "--archive" in extra else None
        print(json.dumps({**verifier.upstream_only(archive), "verified": True}))

    return upstream, archives, run


def _result(capsys):
    lines = capsys.readouterr().out.strip().splitlines()
    return lines[:-1], json.loads(lines[-1])


def test_a_newer_non_member_upstream_only_warns(world, capsys):
    """Mutation: keeping the membership ``require`` (the job reds on every new agy)."""
    upstream, archives, run = world
    run("--archive", str(archives["1.10.0"]))
    annotations, result = _result(capsys)
    assert annotations == [WARNING.format("2.0.0")]
    assert result["latest_release"] == "2.0.0" and result["latest_is_member"] is False
    assert result["verified_member"] == "1.10.0" and result["verified"] is True
    assert f"{RELEASES}/tags/1.10.0" in upstream.calls


def test_the_newest_member_is_fetched_and_its_archive_downloaded_by_tag(world, capsys):
    upstream, _archives, run = world
    run()
    annotations, result = _result(capsys)
    assert annotations == [WARNING.format("2.0.0")]
    assert result["verified_member"] == "1.10.0"
    assert upstream.calls == [LISTING, f"{RELEASES}/tags/1.10.0", f"{DOWNLOAD}1.10.0/{ASSET}"]


def test_a_member_latest_verifies_without_a_warning(world, capsys):
    upstream, archives, run = world
    upstream.latest = "1.10.0"
    run("--archive", str(archives["1.10.0"]))
    annotations, result = _result(capsys)
    assert annotations == []
    assert result["latest_release"] == "1.10.0" and result["latest_is_member"] is True
    assert result["verified_member"] == "1.10.0"


@pytest.mark.parametrize("mismatch", ["asset_digest", "asset_url", "archive"])
@pytest.mark.parametrize("latest", ["2.0.0", "1.10.0"])
def test_a_shipped_member_integrity_mismatch_still_fails(world, capsys, mismatch, latest):
    """The member checks stay ``require``s whether or not the latest upstream is a member.

    Mutation: dropping the member-digest ``require`` (or making it advisory) greens the
    ``asset_digest`` cells.
    """
    upstream, archives, run = world
    upstream.latest = latest
    archive = archives["1.10.0"].read_bytes()
    if mismatch == "asset_digest":
        upstream.add("1.10.0", archive, digest="sha256:" + "0" * 64)
        reason = "vendor asset digest mismatch"
    elif mismatch == "asset_url":
        upstream.add("1.10.0", archive, url=f"https://example.invalid/1.10.0/{ASSET}")
        reason = "vendor asset URL mismatch"
    else:
        archives["1.10.0"].write_bytes(_archive(b"#!/bin/sh\necho substituted\n"))
        reason = "archive digest mismatch"
    with pytest.raises(ValueError, match=reason):
        run("--archive", str(archives["1.10.0"]))
    assert '"verified": true' not in capsys.readouterr().out


def test_a_substituted_executable_inside_a_matching_archive_fails(world, verifier, monkeypatch):
    upstream, archives, run = world
    substituted = _archive(b"#!/bin/sh\necho substituted\n")
    records = verifier.contract()
    newest = next(record for record in records if record["release_version"] == "1.10.0")
    newest["upstream_asset_sha256"] = sha256(substituted).hexdigest()
    upstream.add("1.10.0", substituted)
    archives["1.10.0"].write_bytes(substituted)
    with pytest.raises(ValueError, match="executable digest mismatch"):
        run("--archive", str(archives["1.10.0"]))


def test_the_upstream_job_step_is_blocking():
    """The step reds on a member-integrity failure. Mutation: ``continue-on-error``."""
    job = yaml.safe_load(QUALIFIED.read_text())["jobs"]["upstream"]
    (step,) = [step for step in job["steps"] if "--upstream-only" in step.get("run", "")]
    assert step["run"] == "uv run --locked python scripts/verify_qualified_agy_image.py --upstream-only"
    assert step["working-directory"] == "phase-loop-runtime"
    assert "continue-on-error" not in step and "if" not in step
    assert "continue-on-error" not in job


def test_main_reports_an_upstream_refusal_as_exit_status_one(world, verifier, monkeypatch, capsys):
    upstream, archives, run = world
    records = verifier.contract()
    next(r for r in records if r["release_version"] == "1.10.0")["upstream_asset_sha256"] = "0" * 64
    assert verifier.main(["--upstream-only", "--archive", str(archives["1.10.0"])]) == 1
    assert "verify_qualified_agy_image:" in capsys.readouterr().err


# ------------------------------------------------- PROVFWD: the newest release from the listing

#: One listing for both filters: drafts, prereleases and non-release tags ahead of the newest.
SHARED_LISTING = [
    {"tag_name": "3.0.0", "draft": True, "prerelease": False, "published_at": "2026-11-20T00:00:00Z"},
    {"tag_name": "2.9.0", "draft": False, "prerelease": True, "published_at": "2026-11-19T12:00:00Z"},
    {"tag_name": "nightly", "draft": False, "prerelease": False, "published_at": "2026-11-19T11:00:00Z"},
    {"tag_name": "2.5.0", "draft": None, "prerelease": False, "published_at": "2026-11-19T10:00:00Z"},
    {"tag_name": "2.1.0", "draft": False, "prerelease": False, "published_at": "2026-11-19T09:00:00Z"},
    {"tag_name": "2.0.0", "draft": False, "prerelease": False, "published_at": "2026-11-18T09:00:00Z"},
]


class _Listing:
    """``agy_provenance``'s transport over ``SHARED_LISTING`` (one short page)."""

    def open(self, url, *, accept):
        first = parse_qs(urlsplit(url).query).get("page", ["1"]) == ["1"]
        return io.BytesIO(json.dumps(SHARED_LISTING if first else []).encode())


def test_newest_stable_uses_the_resolvers_stable_filter(verifier):
    """Mutation: ``/releases/latest`` (GitHub's choice), or a filter that keeps a draft or a
    prerelease ahead of the newest stable release."""
    from phase_loop_runtime import agy_provenance as prov
    seen = []
    newest = verifier.newest_stable(lambda url: seen.append(url) or SHARED_LISTING)
    assert newest["tag_name"] == "2.1.0" == prov.stable_releases(_Listing())[0]["tag_name"]
    assert seen == [LISTING]


@pytest.mark.parametrize("listing", [[], [SHARED_LISTING[0], SHARED_LISTING[1]], {"tag_name": "2.0.0"}, None])
def test_a_listing_without_a_stable_release_refuses(verifier, listing):
    with pytest.raises(ValueError, match="listing"):
        verifier.newest_stable(lambda url: listing)


def test_upstream_only_skips_entries_ahead_of_the_newest_stable_release(world, capsys):
    upstream, archives, run = world
    upstream.latest = "1.10.0"
    upstream.ahead = [dict(upstream.releases["2.0.0"], tag_name="3.0.0", prerelease=True),
                      dict(upstream.releases["2.0.0"], tag_name="2.9.0", draft=True)]
    run("--archive", str(archives["1.10.0"]))
    annotations, result = _result(capsys)
    assert annotations == [] and result["latest_release"] == "1.10.0" and result["latest_is_member"] is True


def test_the_result_carries_the_newest_releases_published_at(world, capsys):
    upstream, archives, run = world
    upstream.releases["2.0.0"]["published_at"] = "2026-11-20T01:02:03Z"
    run("--archive", str(archives["1.10.0"]))
    _, result = _result(capsys)
    assert result["latest_published_at"] == "2026-11-20T01:02:03Z" and result["latest_release"] == "2.0.0"


def test_the_verifier_keeps_exactly_its_three_modes(verifier, capsys):
    with pytest.raises(SystemExit):
        verifier.main(["--help"])
    usage = " ".join(capsys.readouterr().out.split())
    assert "(--contract | --release | --upstream-only)" in usage
    assert usage.count("--") == len(re.findall(r"--(?:contract|release|upstream-only|conformance-report|archive|help)",
                                               usage))
