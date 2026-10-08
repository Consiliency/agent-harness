"""`verify_qualified_agy_image.py --upstream-only`: membership is advisory (agent-harness#1333 PR1).

A newer upstream agy release that is not a shipped member only warns; hosts self-qualify it
on first use. The newest SHIPPED member's vendor asset digest, URL and archive stay blocking,
so the scheduled `upstream` job reds on any member-integrity failure and never on membership.

Nothing here reaches the network: the release API and the asset are served in memory, and
the catalog is replaced by synthetic records whose digests match a synthetic archive.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
REPO = Path(__file__).resolve().parents[2]
QUALIFIED = REPO / ".github" / "workflows" / "qualified-agy-image.yml"
RELEASES = "https://api.github.com/repos/google-antigravity/antigravity-cli/releases"
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
    """The release API, by-tag lookups and asset downloads; records every URL."""

    def __init__(self):
        self.releases, self.blobs, self.calls = {}, {}, []
        self.latest = None

    def add(self, version, archive, *, digest=None, url=None):
        url = url or f"{DOWNLOAD}{version}/{ASSET}"
        self.blobs[url] = archive
        self.releases[version] = {"tag_name": version, "assets": [
            {"name": ASSET, "browser_download_url": url,
             "digest": digest or "sha256:" + sha256(archive).hexdigest()}]}

    def urlopen(self, request, timeout=None):
        url = getattr(request, "full_url", request)
        self.calls.append(url)
        if url == f"{RELEASES}/latest":
            return io.BytesIO(json.dumps(self.releases[self.latest]).encode())
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
    monkeypatch.setattr(verifier, "validate_records", lambda **_: records)
    monkeypatch.setattr(verifier, "urlopen", upstream.urlopen)

    def run(*extra):
        monkeypatch.setattr(sys, "argv", ["verify_qualified_agy_image.py", "--upstream-only", *extra])
        verifier.main()

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
    assert upstream.calls == [f"{RELEASES}/latest", f"{RELEASES}/tags/1.10.0", f"{DOWNLOAD}1.10.0/{ASSET}"]


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
    records = verifier.validate_records()
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
    assert step["run"] == "python phase-loop-runtime/scripts/verify_qualified_agy_image.py --upstream-only"
    assert "continue-on-error" not in step and "if" not in step
    assert "continue-on-error" not in job
