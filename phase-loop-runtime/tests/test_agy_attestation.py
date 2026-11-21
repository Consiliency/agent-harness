"""Attestation status and the catalog job's second channel (AGYROLL §1.3; PROVFWD-detail §2, §4.3).

Nothing here reaches the network: every request goes to an in-memory connection that
records the host, target and headers it was given. The measured comparison basis
(PROVFWD-detail §2.2, task SL-1.1) is kept below as redacted evidence: versions, sizes and
digests only.
"""
from __future__ import annotations

from hashlib import sha256, sha512
import io
import json
from urllib.parse import urlsplit

import pytest

from phase_loop_runtime import agy_attestation as att
from phase_loop_runtime import agy_provenance as prov

LINUX_X64 = prov.HostPlatform("linux", "x64", "glibc")
MANIFEST_URL = f"https://{att.MANIFEST_HOST}{att.MANIFEST_PATH}"

#: SL-1.1, measured once on 2026-11-20 for the newest stable release through the pinned
#: openers (public, unauthenticated reads; hashed while streaming; nothing executed). Google's
#: package and the GitHub asset are the same bytes, so the archive basis holds and is the one
#: implemented. One release selects the method; it does not prove the channels stay equal.
MEASURED = {
    "release_version": "1.5.13",
    "manifest_version": "1.5.13",
    "manifest_sha512": "014b37387703acab1f47cd532c8bb60167a6a3537b0f9891de03f1b1ffa9614307bc83c4b"
                       "2f7551273b0877d722716b0cd9e26782f6b2a50705db4f05e18c68f",
    "github_asset": {"size": 100_548_668,
                     "sha256": "7fa9cc6df0d09562693d637c406a86c1b0f52ab3364714b1fd2d79cc6060d4b2",
                     "sha512": "014b37387703acab1f47cd532c8bb60167a6a3537b0f9891de03f1b1ffa9614307bc83c4b"
                               "2f7551273b0877d722716b0cd9e26782f6b2a50705db4f05e18c68f",
                     "member_sha256": "c3fd2c848abf88a243936f33e25bf5970802a7651840b5199318fcd8eb3fdb65"},
    "google_package": {"size": 100_548_668,
                       "sha256": "7fa9cc6df0d09562693d637c406a86c1b0f52ab3364714b1fd2d79cc6060d4b2",
                       "sha512": "014b37387703acab1f47cd532c8bb60167a6a3537b0f9891de03f1b1ffa9614307bc83c4b"
                                 "2f7551273b0877d722716b0cd9e26782f6b2a50705db4f05e18c68f",
                       "member_sha256": "c3fd2c848abf88a243936f33e25bf5970802a7651840b5199318fcd8eb3fdb65"},
}

#: The shape GitHub's REST reference documents for "List attestations" (a trimmed bundle).
DOCUMENTED_ATTESTATIONS = {
    "attestations": [{
        "bundle": {
            "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
            "verificationMaterial": {"tlogEntries": [], "timestampVerificationData": {},
                                     "certificate": {"rawBytes": "MIIC..."}},
            "dsseEnvelope": {"payload": "eyJfdHlwZSI6...", "payloadType": "application/vnd.in-toto+json",
                             "signatures": [{"sig": "MEUC..."}]},
        },
        "repository_id": 1,
        "bundle_url": "https://example.invalid/bundle",
    }],
}


class _Response:
    def __init__(self, status, body):
        self.status, self._body, self.closed = status, io.BytesIO(body), False

    def read(self, n=-1):
        return self._body.read(n)

    def close(self):
        self.closed = True


class _Server:
    """``connection`` for ``att._Opener``: answers by (host, target) and records every request.

    A value is (status, body), a list of them (served in order), or an exception to raise."""

    def __init__(self, routes=None):
        self.routes, self.requests, self.connections = dict(routes or {}), [], []

    def __call__(self, host, port, *, context, timeout):
        self.connections.append((host, port, context))
        server = self

        class Conn:
            def request(self, method, target, headers):
                server.requests.append((method, host, target, dict(headers)))
                self.target = target

            def getresponse(self):
                answer = server.routes[(host, self.target)]
                if isinstance(answer, list):
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                if isinstance(answer, BaseException):
                    raise answer
                return _Response(*answer)

            def close(self):
                pass

        return Conn()


def _opener(server):
    return att._Opener(connection=server, context_factory=lambda: "pinned-context")


def _asset(archive, version="1.5.13"):
    return prov.ReleaseAsset(version, LINUX_X64.asset, f"{prov.DOWNLOAD_PREFIX}{version}/{LINUX_X64.asset}",
                             sha256(archive).hexdigest())


def _attestation_target(asset):
    return f"/repos/{prov.REPO}/attestations/sha256:{asset.digest}"


def _attest(status, body):
    asset = _asset(b"archive")
    server = _Server({(prov.API_HOST, _attestation_target(asset)): (status, body)})
    return server, (lambda: att.attestation_status(asset, _opener(server)))


# -------------------------------------------------------------------- the measured basis

def test_the_measured_basis_is_the_archive_basis():
    """SL-1.1's evidence selects the archive basis: the manifest's sha512 is the GitHub asset's."""
    github, google = MEASURED["github_asset"], MEASURED["google_package"]
    assert MEASURED["manifest_version"] == MEASURED["release_version"]
    assert MEASURED["manifest_sha512"] == github["sha512"] == google["sha512"]
    assert github["sha256"] == google["sha256"] and github["size"] == google["size"]
    assert github["member_sha256"] == google["member_sha256"]


# ------------------------------------------------------------------------- attestation

def test_404_is_absent():
    server, call = _attest(404, b'{"message": "Not Found"}')
    assert call() == "absent"
    ((method, host, target, _),) = server.requests
    assert (method, host) == ("GET", prov.API_HOST) and target.endswith(f"/attestations/sha256:{_asset(b'archive').digest}")


def test_a_non_empty_list_is_present_unverified():
    _, call = _attest(200, json.dumps(DOCUMENTED_ATTESTATIONS).encode())
    assert call() == "present_unverified"


@pytest.mark.parametrize("status,body", [
    (200, b"null"),
    (200, b'{"attestations": []}'),
    (200, b'[{"bundle": {}}]'),
    (200, b'"attestations"'),
    (200, b'{"attestations": {"bundle": {}}}'),
    (200, b'{"attestations": [}'),
    (403, b'{"message": "API rate limit exceeded"}'),
    (500, b""),
])
def test_an_empty_list_a_non_object_or_another_status_is_unavailable(status, body):
    """Mutation: reading an empty list as ``absent``, or a rate-limited answer as a status."""
    _, call = _attest(status, body)
    with pytest.raises(prov.ProvenanceError) as exc:
        call()
    assert str(exc.value) == prov.UNAVAILABLE


def test_a_200_null_body_is_unavailable_while_a_404_is_absent():
    """Review fix 1. JSON ``null`` decodes to ``None``; it must not read as the 404 answer.
    Mutation: returning ``None`` for the absent status."""
    _, control = _attest(404, b"null")
    assert control() == "absent"
    _, call = _attest(200, b"null")
    with pytest.raises(prov.ProvenanceError) as exc:
        call()
    assert str(exc.value) == prov.UNAVAILABLE


def test_an_oversized_body_is_unavailable(monkeypatch):
    monkeypatch.setattr(prov, "MAX_LISTING_BYTES", 64)
    body = json.dumps({"attestations": [{"bundle": "x" * 64}]}).encode()
    _, call = _attest(200, body)
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        call()


@pytest.mark.parametrize("error", [OSError("reset"), TimeoutError("slow"), ConnectionRefusedError()])
def test_a_network_error_is_unavailable(error):
    asset = _asset(b"archive")
    server = _Server({(prov.API_HOST, _attestation_target(asset)): error})
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        att.attestation_status(asset, _opener(server))


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_refused_and_never_followed(status):
    """Mutation: following ``Location`` (the opener has no redirect allowlist to follow)."""
    server, call = _attest(status, b"")
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        call()
    assert len(server.requests) == 1


@pytest.mark.parametrize("url", [
    f"https://github.com/{prov.REPO}/releases",
    "https://release-assets.githubusercontent.com/x",
    "https://objects.githubusercontent.com/x",
    "https://evil.example/manifests/linux_amd64.json",
    f"http://{prov.API_HOST}/repos",
    f"https://{prov.API_HOST}:8443/repos",
    f"https://user:pw@{prov.API_HOST}/repos",
    f"https://{att.MANIFEST_HOST}:notaport/x",
])
def test_a_host_outside_the_three_or_a_non_https_url_is_refused(url):
    server = _Server()
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _opener(server).open(url, accept="*/*")
    assert server.connections == []


def test_exactly_three_hosts_are_allowed():
    assert att.ALLOWED_HOSTS == {prov.API_HOST, att.MANIFEST_HOST, "storage.googleapis.com"}


def test_no_credential_or_proxy_reaches_the_request(monkeypatch, tmp_path):
    """Mutation: urllib (honours *_proxy and .netrc), or an Authorization header."""
    (tmp_path / ".netrc").write_text(f"machine {prov.API_HOST} login x password SECRET\n")
    for key, value in {"HOME": str(tmp_path), "GITHUB_TOKEN": "SECRET", "GH_TOKEN": "SECRET",
                       "HTTPS_PROXY": "http://proxy.invalid:3128", "https_proxy": "http://proxy.invalid:3128",
                       "ALL_PROXY": "http://proxy.invalid:3128"}.items():
        monkeypatch.setenv(key, value)
    server, call = _attest(404, b"")
    assert call() == "absent"
    ((_, host, _, headers),) = server.requests
    assert host == prov.API_HOST and server.connections[0][:2] == (prov.API_HOST, 443)
    assert "Authorization" not in headers and "SECRET" not in json.dumps(headers)
    assert headers["User-Agent"] == prov.USER_AGENT


def test_tls_uses_agy_provenances_trust_context_at_call_time(monkeypatch):
    server = _Server({(prov.API_HOST, _attestation_target(_asset(b"archive"))): (404, b"")})
    monkeypatch.setattr(prov, "_trust_context", lambda: "compiled-in-store")
    assert att.attestation_status(_asset(b"archive"), att._Opener(connection=server)) == "absent"
    assert server.connections[0][2] == "compiled-in-store"


# ---------------------------------------------------------------------- second channel

def _package(content=b"agy archive bytes"):
    return content


def _manifest(version="1.5.13", package=None, *, url=None, digest=None):
    package = _package() if package is None else package
    return {"version": version,
            "url": url or f"{att.MANIFEST_DOWNLOAD_PREFIX}{version}-5999302598852608/linux-x64/cli_linux_x64.tar.gz",
            "sha512": digest or sha512(package).hexdigest()}


def _channel(manifests, package=None, *, package_status=200):
    """A server with ``manifests`` (served in order) and the package each one names."""
    package = _package() if package is None else package
    manifests = manifests if isinstance(manifests, list) else [manifests]
    routes = {(att.MANIFEST_HOST, att.MANIFEST_PATH):
              [(200, m if isinstance(m, bytes) else json.dumps(m).encode()) for m in manifests]}
    for m in manifests:
        if isinstance(m, dict) and isinstance(m.get("url"), str) and m["url"].startswith("https://storage.googleapis.com/"):
            routes[("storage.googleapis.com", m["url"][len("https://storage.googleapis.com"):])] = (package_status, package)
    return _Server(routes)


def _second(server, archive, member="m" * 64, host=LINUX_X64):
    return att.second_channel_status(_asset(archive), member, host=host, transport=_opener(server))


def test_same_version_and_equal_is_match():
    archive = _package()
    server = _channel(_manifest())
    assert _second(server, archive) == "match"
    hosts = [host for _, host, _, _ in server.requests]
    assert hosts == [att.MANIFEST_HOST, "storage.googleapis.com", att.MANIFEST_HOST]


def test_same_version_and_different_is_a_mismatch():
    """Google's package is self-consistent but is not the GitHub asset (archive basis)."""
    github_archive, google_package = b"github bytes", b"google bytes"
    server = _channel(_manifest(package=google_package), google_package)
    with pytest.raises(prov.ProvenanceError) as exc:
        _second(server, github_archive)
    assert str(exc.value) == att.SECOND_CHANNEL_MISMATCH


def test_another_version_is_not_listed_without_fetching_the_package():
    server = _channel(_manifest(version="1.5.14"))
    assert _second(server, _package()) == "not_listed"
    assert [host for _, host, _, _ in server.requests] == [att.MANIFEST_HOST]


def test_a_manifest_that_moves_on_between_its_two_reads_is_not_listed():
    """``not_listed`` is not corroboration: a match is reported only for a version the
    manifest still names after the comparison. Mutation: trusting the first read alone."""
    first, moved = _manifest(), _manifest(version="1.5.14")
    server = _channel([first, moved])
    assert _second(server, _package()) == "not_listed"
    server = _channel([_manifest(package=b"different bytes"), moved], b"different bytes")
    assert _second(server, _package()) == "not_listed"


def test_a_same_version_manifest_that_changes_between_reads_is_unavailable():
    first = _manifest()
    changed = dict(first, url=first["url"].replace("5999302598852608", "1"))
    server = _channel([first, changed])
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())


@pytest.mark.parametrize("platform", [
    prov.HostPlatform("linux", "arm64", "glibc"), prov.HostPlatform("linux", "x64", "musl"),
])
def test_a_platform_without_a_manifest_is_not_listed_with_no_request(platform):
    server = _Server()
    assert _second(server, _package(), host=platform) == "not_listed"
    assert server.requests == [] and server.connections == []


@pytest.mark.parametrize("body", [
    b"null", b"[]", b'"x"', b"{", b"{}",
    json.dumps(dict(_manifest(), version="1.5")).encode(),
    json.dumps(dict(_manifest(), version="1.5.13\n")).encode(),
    json.dumps(dict(_manifest(), version="１.5.13")).encode(),
    json.dumps(dict(_manifest(), version=1513)).encode(),
    json.dumps(dict(_manifest(), url="https://storage.googleapis.com/other-bucket/x.tar.gz")).encode(),
    json.dumps(dict(_manifest(), url="https://evil.example/antigravity-public/antigravity-cli/x")).encode(),
    json.dumps(dict(_manifest(), url=att.MANIFEST_DOWNLOAD_PREFIX + "../other/x.tar.gz")).encode(),
    json.dumps(dict(_manifest(), url=att.MANIFEST_DOWNLOAD_PREFIX + "x.tar.gz?alt=media")).encode(),
    json.dumps(dict(_manifest(), sha512="0" * 127)).encode(),
    json.dumps(dict(_manifest(), sha512="g" * 128)).encode(),
    json.dumps(dict(_manifest(), sha512=None)).encode(),
])
def test_a_malformed_manifest_is_unavailable(body):
    server = _Server({(att.MANIFEST_HOST, att.MANIFEST_PATH): (200, body)})
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())
    assert [host for _, host, _, _ in server.requests] == [att.MANIFEST_HOST]


def test_an_uppercase_sha512_is_read_as_the_same_digest():
    manifest = _manifest()
    server = _channel(dict(manifest, sha512=manifest["sha512"].upper()))
    assert _second(server, _package()) == "match"


def test_an_oversized_manifest_is_unavailable():
    padded = json.dumps(dict(_manifest(), padding="x" * att.MAX_MANIFEST_BYTES)).encode()
    server = _Server({(att.MANIFEST_HOST, att.MANIFEST_PATH): (200, padded)})
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())


@pytest.mark.parametrize("answer", [(503, b""), (404, b""), (302, b""), OSError("unreachable")])
def test_an_unreachable_manifest_is_unavailable(answer):
    server = _Server({(att.MANIFEST_HOST, att.MANIFEST_PATH): answer})
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())


@pytest.mark.parametrize("status", [403, 404, 500, 302])
def test_an_unreachable_package_is_unavailable(status):
    server = _channel(_manifest(), package_status=status)
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())


def test_a_package_that_is_not_the_manifests_is_unavailable_not_a_match():
    """The second channel disagrees with itself: it can neither corroborate nor contradict."""
    server = _channel(_manifest(digest=sha512(b"other").hexdigest()))
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())


def test_an_oversized_package_is_unavailable(monkeypatch):
    monkeypatch.setattr(prov, "MAX_ARCHIVE_BYTES", 8)
    server = _channel(_manifest())
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _second(server, _package())


def test_the_second_channel_sends_no_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "SECRET")
    server = _channel(_manifest())
    assert _second(server, _package()) == "match"
    assert all("Authorization" not in headers for _, _, _, headers in server.requests)


def test_the_status_vocabularies_are_closed():
    assert att.ATTESTATION_STATUSES == ("absent", "present_unverified", "not_checked")
    assert att.SECOND_CHANNEL_STATUSES == ("match", "not_listed", "not_checked")
    assert att.SECOND_CHANNEL_MISMATCH == "agy_provenance_second_channel_mismatch"


# ------------------------------------------- the package URL as it will be requested (review fix 2)

PACKAGE_PREFIX = att.MANIFEST_DOWNLOAD_PREFIX


@pytest.mark.parametrize("suffix", [
    # percent-encoded dot segments
    "%2e%2e/other-bucket/x.tar.gz", "%2E%2E/x.tar.gz", ".%2e/x.tar.gz", "%2e/x.tar.gz",
    "1.5.13/%2e%2e/%2e%2e/x.tar.gz",
    # mixed separators
    "1.5.13\\..\\..\\x.tar.gz", "1.5.13/..\\x.tar.gz", "1.5.13\\linux-x64/cli_linux_x64.tar.gz",
    # characters urlsplit drops, so a raw check would pass ".<TAB>." and the request would carry ".."
    ".\t./other-bucket/x.tar.gz", "..\t/x.tar.gz", ".\n./x.tar.gz", "1.5.13/.\r./x.tar.gz",
    "1.5.13 /x.tar.gz", "\x7f/x.tar.gz", "\u00e9/x.tar.gz",
    # paths that normalize outside the prefix, or are not plain names
    "1.5.13/../../../other-bucket/x.tar.gz", "../antigravity-cli/x.tar.gz", "./x.tar.gz",
    "1.5.13//x.tar.gz", "x.tar.gz/",
    # a query or fragment
    "x.tar.gz?alt=media", "x.tar.gz#fragment", "x.tar.gz#",
])
def test_a_package_url_that_could_leave_the_prefix_is_refused_before_any_package_request(suffix):
    url = PACKAGE_PREFIX + suffix
    server = _Server({(att.MANIFEST_HOST, att.MANIFEST_PATH): (200, json.dumps(dict(_manifest(), url=url)).encode())})
    with pytest.raises(prov.ProvenanceError) as exc:
        _second(server, _package())
    assert str(exc.value) == prov.UNAVAILABLE
    assert [host for _, host, _, _ in server.requests] == [att.MANIFEST_HOST]  # zero package requests
    direct = _Server()  # the package fetch re-checks the effective URL before it connects
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        att._package_digests(_opener(direct), url)
    assert direct.connections == [] and direct.requests == []


def test_the_tab_case_is_a_parent_segment_once_parsed():
    """Why the check runs on the parsed request: ``urlsplit`` removes the tab."""
    assert "/../" in urlsplit(PACKAGE_PREFIX + ".\t./other-bucket/x.tar.gz").path


def test_the_published_package_url_shape_is_accepted():
    url = PACKAGE_PREFIX + "1.5.13-5999302598852608/linux-x64/cli_linux_x64.tar.gz"
    assert att._package_target(url) == url


@pytest.mark.parametrize("url", [
    f"https://{prov.API_HOST}/repos\t/x", f"https://{att.PACKAGE_HOST}/a\n/b", f"https://{prov.API_HOST}/ x",
    f"https://{prov.API_HOST}/\x00", f"https://{att.MANIFEST_HOST}/manifests/linux_amd64.json\r",
    f"https://{prov.API_HOST}/\u00e9",
])
def test_the_opener_refuses_control_and_non_ascii_characters_before_parsing(url):
    server = _Server()
    with pytest.raises(prov.ProvenanceError, match=prov.UNAVAILABLE):
        _opener(server).open(url, accept="*/*")
    assert server.connections == []
