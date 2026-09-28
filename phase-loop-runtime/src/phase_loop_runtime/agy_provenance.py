"""Provenance of an upstream agy release asset (agent-harness#1076).

Nothing here executes anything. It answers one question in the coordinator process:
is this exact image digest the ``antigravity`` member of a stable upstream release
asset for THIS host's platform, whose archive digest equals the digest GitHub
publishes for that asset?

The transport is pinned. It uses ``http.client`` (which has no proxy support), sends no
``Authorization`` header, never reads ``.netrc``, credential helpers, token or proxy
variables, and verifies TLS against the interpreter's compiled-in OpenSSL trust store
(``ssl.get_default_verify_paths().openssl_*``), not ``SSL_CERT_FILE``/``SSL_CERT_DIR``.
Integrity rests on the published digest, not the URL; redirects are followed over https
only, to a fixed host allowlist, a bounded number of times.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import glob
import http.client
import json
import os
import platform as _platform
import posixpath
import re
import ssl
import sys
import tarfile
from urllib.parse import urlsplit

REPO = "google-antigravity/antigravity-cli"
API_HOST = "api.github.com"
RELEASES_PATH = f"/repos/{REPO}/releases?per_page=30"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
# GitHub serves release downloads by a 302 from github.com to its asset CDN.
REDIRECT_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com",
                            "objects.githubusercontent.com"})
MAX_REDIRECTS = 3
# The member digest is only knowable by downloading each archive, so a tampered image
# (which matches nothing) would otherwise download every release on every first use.
# At least 2, so that a non-pinned in-window build can exercise the path live.
RECENCY_WINDOW = 4
MAX_LISTING_BYTES = 4_000_000
MAX_ARCHIVE_BYTES = 128_000_000
MAX_MEMBER_BYTES = 250_000_000
MEMBER_NAME = "antigravity"
USER_AGENT = "agent-harness-agy-provenance"

UNAVAILABLE = "gemini_heartbeat_provenance_unavailable"
UNVERIFIED = "gemini_heartbeat_provenance_unverified"
UNSUPPORTED = "gemini_heartbeat_platform_unsupported"

_TAG = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")


class ProvenanceError(ValueError):
    """A fixed, content-free provenance diagnostic."""


@dataclass(frozen=True)
class HostPlatform:
    os: str
    arch: str
    libc: str

    @property
    def name(self) -> str:
        return f"{self.os}-{self.arch}" + ("-musl" if self.libc == "musl" else "")

    @property
    def asset(self) -> str:
        return f"agy_cli_{self.os}_{self.arch}" + ("_musl" if self.libc == "musl" else "") + ".tar.gz"


@dataclass(frozen=True)
class ReleaseAsset:
    version: str
    name: str
    url: str
    digest: str  # the archive's hex sha256, from GitHub's per-asset ``digest``


@dataclass(frozen=True)
class Provenance:
    """A verified match: ``image_sha256`` is the member of ``asset``."""
    image_sha256: str
    platform: str
    asset: ReleaseAsset


_ARCH = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}


def detect_platform(*, uname=os.uname, libc_ver=_platform.libc_ver,
                    musl_loaders=lambda: glob.glob("/lib/ld-musl-*.so.1")) -> HostPlatform:
    """The RUNNING host's platform (D4). Reads no config and no environment."""
    info = uname()
    if info.sysname != "Linux" or info.machine not in _ARCH:
        raise ProvenanceError(UNSUPPORTED)
    libc = libc_ver(sys.executable)[0]
    if libc == "glibc":
        kind = "glibc"
    elif musl_loaders():
        kind = "musl"
    else:
        raise ProvenanceError(UNSUPPORTED)
    return HostPlatform("linux", _ARCH[info.machine], kind)


def _trust_context() -> ssl.SSLContext:
    paths = ssl.get_default_verify_paths()
    cafile = paths.openssl_cafile if paths.openssl_cafile and os.path.isfile(paths.openssl_cafile) else None
    capath = paths.openssl_capath if paths.openssl_capath and os.path.isdir(paths.openssl_capath) else None
    if cafile is None and capath is None:
        raise ProvenanceError(UNAVAILABLE)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=cafile, capath=capath)
    return context


class _Transport:
    """https GET with no credentials, no proxy and the compiled-in trust store."""

    def __init__(self, *, connection=http.client.HTTPSConnection, context_factory=_trust_context,
                 timeout: float = 60):
        self.connection, self.context_factory, self.timeout = connection, context_factory, timeout

    def open(self, url: str, *, accept: str):
        context = self.context_factory()
        for _hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname not in REDIRECT_HOSTS | {API_HOST} \
                    or parts.port not in (None, 443) or parts.username or parts.password:
                raise ProvenanceError(UNAVAILABLE)
            conn = self.connection(parts.hostname, 443, context=context, timeout=self.timeout)
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            conn.request("GET", target, headers={"Accept": accept, "User-Agent": USER_AGENT})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                # The Location of an asset download is a signed URL: never logged.
                url = response.getheader("Location") or ""
                response.close()
                conn.close()
                continue
            if response.status != 200:
                response.close()
                conn.close()
                raise ProvenanceError(UNAVAILABLE)
            return response
        raise ProvenanceError(UNAVAILABLE)


def stable_releases(transport: _Transport, *, window: int = RECENCY_WINDOW) -> list[dict]:
    """The newest ``window`` stable releases (no prerelease, no draft), newest first."""
    try:
        response = transport.open(f"https://{API_HOST}{RELEASES_PATH}", accept="application/vnd.github+json")
        body = response.read(MAX_LISTING_BYTES + 1)
        response.close()
        if len(body) > MAX_LISTING_BYTES:
            raise ProvenanceError(UNAVAILABLE)
        releases = json.loads(body)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError(UNAVAILABLE) from exc
    if not isinstance(releases, list):
        raise ProvenanceError(UNAVAILABLE)
    stable = [r for r in releases if isinstance(r, dict) and r.get("draft") is False
              and r.get("prerelease") is False and isinstance(r.get("tag_name"), str)
              and _TAG.fullmatch(r["tag_name"])]
    return stable[:window]


def release_by_tag(transport: _Transport, tag: str) -> dict:
    """One stable release by tag (the upstream watch re-fetches already-pinned members)."""
    if not _TAG.fullmatch(tag):
        raise ProvenanceError(UNVERIFIED)
    try:
        response = transport.open(f"https://{API_HOST}/repos/{REPO}/releases/tags/{tag}",
                                  accept="application/vnd.github+json")
        body = response.read(MAX_LISTING_BYTES + 1)
        response.close()
        release = json.loads(body)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError(UNAVAILABLE) from exc
    if (not isinstance(release, dict) or release.get("draft") is not False
            or release.get("prerelease") is not False or release.get("tag_name") != tag):
        raise ProvenanceError(UNVERIFIED)
    return release


def release_asset(release: dict, host: HostPlatform) -> ReleaseAsset:
    """The exact platform asset of one release, with its URL and digest checked."""
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ProvenanceError(UNVERIFIED)
    matches = [a for a in release.get("assets") or () if isinstance(a, dict) and a.get("name") == host.asset]
    if len(matches) != 1:
        raise ProvenanceError(UNVERIFIED)
    asset, = matches
    url, digest = asset.get("browser_download_url"), asset.get("digest")
    if url != f"{DOWNLOAD_PREFIX}{tag}/{host.asset}":
        raise ProvenanceError(UNVERIFIED)
    match = _DIGEST.fullmatch(digest) if isinstance(digest, str) else None
    if match is None:
        raise ProvenanceError(UNVERIFIED)
    return ReleaseAsset(tag, host.asset, url, match.group(1))


class _HashingReader:
    """Feed every byte read by the tar reader through the archive digest, with a cap."""

    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, sha256(), 0

    def read(self, n=-1):
        chunk = self.stream.read(1024 * 1024 if n is None or n < 0 else n)
        self.size += len(chunk)
        if self.size > MAX_ARCHIVE_BYTES:
            raise ProvenanceError(UNVERIFIED)
        self.digest.update(chunk)
        return chunk

    def drain(self):
        while self.read(1024 * 1024):
            pass


def _normalized(name: str) -> str:
    return posixpath.normpath(name.lstrip("/"))


def read_member(stream, asset: ReleaseAsset, *, keep_bytes: bool = False) -> tuple[str, bytes | None]:
    """Stream-hash the archive and its one ``antigravity`` member; never extract to disk.

    Exactly one member may normalize to ``antigravity`` and it must be a regular file;
    a duplicate, a link or a device of that name refuses. The archive digest must equal
    the asset's published digest before the member digest is returned.
    """
    reader = _HashingReader(stream)
    member_digest, member_bytes, seen = None, None, 0
    try:
        with tarfile.open(fileobj=reader, mode="r|gz") as bundle:
            for member in bundle:
                if _normalized(member.name) != MEMBER_NAME:
                    continue
                seen += 1
                if seen > 1 or not member.isreg() or member.size > MAX_MEMBER_BYTES:
                    raise ProvenanceError(UNVERIFIED)
                handle = bundle.extractfile(member)
                if handle is None:
                    raise ProvenanceError(UNVERIFIED)
                h, parts, size = sha256(), [], 0
                while chunk := handle.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_MEMBER_BYTES:
                        raise ProvenanceError(UNVERIFIED)
                    h.update(chunk)
                    if keep_bytes:
                        parts.append(chunk)
                member_digest = h.hexdigest()
                member_bytes = b"".join(parts) if keep_bytes else None
        reader.drain()
    except (tarfile.TarError, EOFError, OSError, http.client.HTTPException) as exc:
        raise ProvenanceError(UNAVAILABLE if isinstance(exc, (OSError, http.client.HTTPException)) else UNVERIFIED) from exc
    if seen != 1 or member_digest is None:
        raise ProvenanceError(UNVERIFIED)
    if reader.digest.hexdigest() != asset.digest:
        raise ProvenanceError(UNVERIFIED)
    return member_digest, member_bytes


def fetch_member(transport: _Transport, asset: ReleaseAsset, *, keep_bytes: bool = False):
    try:
        response = transport.open(asset.url, accept="application/octet-stream")
    except (OSError, http.client.HTTPException) as exc:
        raise ProvenanceError(UNAVAILABLE) from exc
    try:
        return read_member(response, asset, keep_bytes=keep_bytes)
    finally:
        response.close()


def find_provenance(image_sha256: str, *, host: HostPlatform, transport: _Transport | None = None,
                    cached_member=lambda asset: None, remember_member=lambda asset, member: None,
                    window: int = RECENCY_WINDOW) -> Provenance:
    """Match ``image_sha256`` against the in-window stable releases for ``host``.

    ``cached_member``/``remember_member`` are the store's authenticated member-digest
    cache (keyed on the asset digest and runtime identity), so a repeat miss does not
    download again. Any fetch failure refuses UNAVAILABLE; no match refuses UNVERIFIED.
    """
    transport = transport or _Transport()
    for release in stable_releases(transport, window=window):
        try:
            asset = release_asset(release, host)
        except ProvenanceError:
            continue
        member = cached_member(asset)
        if member is None:
            member, _ = fetch_member(transport, asset)
            remember_member(asset, member)
        if member == image_sha256:
            return Provenance(image_sha256, host.name, asset)
    raise ProvenanceError(UNVERIFIED)
