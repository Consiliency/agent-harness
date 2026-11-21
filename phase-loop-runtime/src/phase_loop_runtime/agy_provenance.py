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

Any listed stable release can be the match (AGYROLL §1.2): the lookup walks the paged listing
forward, hint first, within a per-call download budget and a rolling daily cap whose ledger
the caller keeps.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import glob
import http.client
from itertools import chain
import json
import os
import platform as _platform
import posixpath
import re
import ssl
import sys
import tarfile
import time
from urllib.parse import urlsplit
import zlib

REPO = "google-antigravity/antigravity-cli"
API_HOST = "api.github.com"
RELEASES_PATH = f"/repos/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
# GitHub serves release downloads by a 302 from github.com to its asset CDN.
REDIRECT_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com",
                            "objects.githubusercontent.com"})
MAX_REDIRECTS = 3
# The listing is read page by page, in API order, and never past MAX_LISTED entries.
LISTING_PAGE = 100
MAX_LISTED = 300
MAX_LISTING_BYTES = 4_000_000  # per page
# The member digest is only knowable by downloading each archive, so a tampered image (which
# matches nothing) would otherwise download every release. Each call fetches at most
# DOWNLOAD_BUDGET uncached archives, and each (store, image) at most TOTAL_DOWNLOAD_CAP in any
# TOTAL_DOWNLOAD_WINDOW_S: about 3 GB a day at MAX_ARCHIVE_BYTES. Both refusals are retryable.
DOWNLOAD_BUDGET = 2
TOTAL_DOWNLOAD_CAP = 12
TOTAL_DOWNLOAD_WINDOW_S = 86_400
BUDGET_EXHAUSTED = "budget_exhausted"
DOWNLOAD_CAP_REACHED = "download_cap_reached"
# The three agy size bounds (AGYFRESH §1.1), each defined only here. Every reader looks them
# up as ``agy_provenance.<NAME>`` when it runs, so patching this module moves every reader.
# They are ceilings, not a measure of what a host can afford.
#
# Largest compressed release asset.
MAX_ARCHIVE_BYTES = 256_000_000
# Largest agy image accepted anywhere: the archive member here, the seat readers
# (``gemini_heartbeat``, ``agy_integrity``) and, as a tested-equal script literal,
# ``scripts/verify_qualified_agy_image.py``. Upstream's image passed 250 MB at 1.5.11
# (268,841,672 bytes). The member is hashed in bounded chunks, so here this bounds work, not
# memory; no reader holds the member (the upstream watch streams it to a sink, ROLLJOB).
MAX_MEMBER_BYTES = 512_000_000
# Largest decompressed tar stream read from one archive: every byte the tar parser is given
# (headers, extension records, padding, skipped members and the member) counts, and so does
# the sum of the declared member sizes. The compressed bound alone does not bound this.
MAX_EXPANDED_BYTES = 1_024_000_000
# What the tar parser may keep while reading one archive (review of AGYFRESH r2, finding 1):
# header blocks of any kind, bytes of extension records (PAX, GNU long name and link), and
# consecutive extension headers before one member (the parser recurses once per header).
# Sparse members are refused outright: their maps are parser metadata of unbounded length.
MAX_ARCHIVE_ENTRIES = 4096
MAX_ARCHIVE_METADATA_BYTES = 4_194_304
MAX_EXTENSION_CHAIN = 8
MEMBER_NAME = "antigravity"
USER_AGENT = "agent-harness-agy-provenance"

UNAVAILABLE = "gemini_heartbeat_provenance_unavailable"
UNVERIFIED = "gemini_heartbeat_provenance_unverified"
UNSUPPORTED = "gemini_heartbeat_platform_unsupported"

_TAG = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")
_HINT = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+)(?:[-+].*)?", re.DOTALL)


class ProvenanceError(ValueError):
    """A fixed, content-free provenance diagnostic.

    ``str(exc)`` is the code. ``reason`` refines a refusal without changing its code:
    ``BUDGET_EXHAUSTED`` and ``DOWNLOAD_CAP_REACHED`` mark the two retryable ``UNVERIFIED``
    refusals; ``None`` is the definitive one.
    """

    def __init__(self, code, reason=None):
        super().__init__(code)
        self.reason = reason


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
    """A verified match: ``image_sha256`` is the member of ``asset``.

    ``attestation`` and ``second_channel`` are recorded statuses (``agy_attestation``), never
    admission criteria. First use records the attestation; only the catalog job checks the
    second channel, so here it stays ``not_checked``."""
    image_sha256: str
    platform: str
    asset: ReleaseAsset
    attestation: str = "not_checked"
    second_channel: str = "not_checked"


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


def version_hint(subject_path) -> str | None:
    """The version a subject's install path names, or ``None``: the first component of its
    real path that matches ``^(\\d+\\.\\d+\\.\\d+)(?:[-+].*)?$``.

    It resolves the path and nothing else: it opens nothing, executes nothing and never reads
    ``--version``. A hint only orders the candidates; admission is still the member digest."""
    for component in os.fsdecode(os.path.realpath(subject_path)).split(os.sep):
        match = _HINT.fullmatch(component)
        if match is not None:
            return match.group(1)
    return None


def _is_stable(release) -> bool:
    return (isinstance(release, dict) and release.get("draft") is False and release.get("prerelease") is False
            and isinstance(release.get("tag_name"), str) and _TAG.fullmatch(release["tag_name"]) is not None)


def _listing_page(transport: _Transport, page: int) -> list:
    """One page of the release listing, within ``MAX_LISTING_BYTES``."""
    try:
        response = transport.open(f"https://{API_HOST}{RELEASES_PATH}?per_page={LISTING_PAGE}&page={page}",
                                  accept="application/vnd.github+json")
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
    return releases


def _stable(transport: _Transport):
    """Stable releases in API order (newest first), one page at a time, as they are needed.

    A page is requested only when the previous ones are used up; the listing ends at a short
    page or after ``MAX_LISTED`` scanned entries, stable or not."""
    scanned, page = 0, 1
    while scanned < MAX_LISTED:
        releases = _listing_page(transport, page)
        for release in releases[:MAX_LISTED - scanned]:
            if _is_stable(release):
                yield release
        scanned += len(releases)
        if len(releases) < LISTING_PAGE:
            return
        page += 1


def stable_releases(transport: _Transport, *, limit: int | None = None) -> list[dict]:
    """Every listed stable release (no prerelease, no draft), newest first, or the first ``limit``.

    ``limit=1`` costs one request when the first page holds a stable release."""
    releases = []
    for release in _stable(transport):
        releases.append(release)
        if limit is not None and len(releases) >= limit:
            break
    return releases


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


# Every streaming read below takes at most one chunk. The tar parser and the decompressor each
# hold a few chunks at a time, so a read holds about seven chunks at its peak, whatever the
# member's size: 256 KiB keeps that under 2 MiB (EC-ROLLJOB-9: the watch streams each member).
_CHUNK_BYTES = 256 * 1024


class _HashingReader:
    """Feed every byte read by the tar reader through the archive digest, with a cap."""

    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, sha256(), 0

    def read(self, n=-1):
        chunk = self.stream.read(_CHUNK_BYTES if n is None or n < 0 else n)
        self.size += len(chunk)
        if self.size > MAX_ARCHIVE_BYTES:
            raise ProvenanceError(UNVERIFIED)
        self.digest.update(chunk)
        return chunk

    def drain(self):
        while self.read(_CHUNK_BYTES):
            pass


class _ExpandedReader:
    """Gunzip below the tar parser, counting every decompressed byte handed to it.

    Each read inflates at most one chunk, so the count is checked before the parser holds
    the bytes: headers, extension records, padding, skipped members and the member itself
    together stay within ``MAX_EXPANDED_BYTES``, however small the compressed input is.
    """

    def __init__(self, compressed):
        self.compressed, self.size = compressed, 0
        self.inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def read(self, n=-1):
        if n == 0:
            return b""
        limit = _CHUNK_BYTES if n is None or n < 0 else min(n, _CHUNK_BYTES)
        while not self.inflate.eof:
            source = self.inflate.unconsumed_tail or self.compressed.read(_CHUNK_BYTES)
            chunk = self.inflate.decompress(source, limit)
            if chunk:
                self.size += len(chunk)
                if self.size > MAX_EXPANDED_BYTES:
                    raise ProvenanceError(UNVERIFIED)
                return chunk
            if not source:
                raise ProvenanceError(UNVERIFIED)  # the compressed stream ended mid-member
        return b""


_EXTENSION_TYPES = frozenset({tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK,
                              tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE})


def _bounded_tarinfo():
    """A ``TarInfo`` class for one archive read that bounds what the parser keeps.

    Every header block, extension headers included, passes ``_proc_member`` before the
    parser reads the record it announces, so the entry, metadata and chain bounds are
    checked before that allocation.
    """
    budget = {"entries": 0, "metadata": 0, "chain": 0}

    class _BoundedTarInfo(tarfile.TarInfo):
        def _proc_member(self, archive):
            budget["entries"] += 1
            if (budget["entries"] > MAX_ARCHIVE_ENTRIES or self.size < 0
                    or self.type == tarfile.GNUTYPE_SPARSE):
                raise ProvenanceError(UNVERIFIED)
            if self.type in _EXTENSION_TYPES:
                budget["chain"] += 1
                budget["metadata"] += self.size
                if (budget["chain"] > MAX_EXTENSION_CHAIN
                        or budget["metadata"] > MAX_ARCHIVE_METADATA_BYTES):
                    raise ProvenanceError(UNVERIFIED)
            else:
                budget["chain"] = 0
            return super()._proc_member(archive)

        def _refuse_sparse(self, *_args):
            raise ProvenanceError(UNVERIFIED)

        # PAX-encoded sparse maps (GNU formats 0.0, 0.1 and 1.0) are refused like type 'S'.
        _proc_gnusparse_00 = _proc_gnusparse_01 = _proc_gnusparse_10 = _refuse_sparse

    return _BoundedTarInfo


def _normalized(name: str) -> str:
    return posixpath.normpath(name.lstrip("/"))


def _write_all(sink: int, chunk: bytes) -> None:
    view = memoryview(chunk)
    while view:
        written = os.write(sink, view)
        if written <= 0:
            raise OSError("agy member sink short write")
        view = view[written:]


def read_member(stream, asset: ReleaseAsset, *, sink: int | None = None) -> str:
    """Stream-hash the archive and its one ``antigravity`` member; never extract to disk.
    Returns the member's sha256.

    With ``sink`` (a writable descriptor), each member chunk is written to it as it is
    hashed, so the caller can build a sealed image without holding the member (EC-ROLLJOB-9).
    The archive digest still decides the result: on any refusal the caller discards the sink.

    Exactly one member may normalize to ``antigravity`` and it must be a regular file;
    a duplicate, a link or a device of that name refuses. The archive digest must equal
    the asset's published digest before the member digest is returned.

    Bounds (AGYFRESH §1.1), all read at call time: compressed bytes ``MAX_ARCHIVE_BYTES``;
    decompressed bytes given to the tar parser, and separately the declared sizes of all
    members, ``MAX_EXPANDED_BYTES``; the member ``MAX_MEMBER_BYTES``; header blocks,
    extension-record bytes and extension chains as ``_bounded_tarinfo`` says.
    """
    reader = _HashingReader(stream)
    member_digest, seen, declared = None, 0, 0
    try:
        with tarfile.open(fileobj=_ExpandedReader(reader), mode="r|", bufsize=_CHUNK_BYTES,
                          tarinfo=_bounded_tarinfo()) as bundle:
            for member in bundle:
                declared += member.size
                if declared > MAX_EXPANDED_BYTES:
                    raise ProvenanceError(UNVERIFIED)
                if _normalized(member.name) != MEMBER_NAME:
                    continue
                seen += 1
                if seen > 1 or not member.isreg() or member.size > MAX_MEMBER_BYTES:
                    raise ProvenanceError(UNVERIFIED)
                handle = bundle.extractfile(member)
                if handle is None:
                    raise ProvenanceError(UNVERIFIED)
                h, size = sha256(), 0
                while chunk := handle.read(_CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_MEMBER_BYTES:
                        raise ProvenanceError(UNVERIFIED)
                    h.update(chunk)
                    if sink is not None:
                        _write_all(sink, chunk)
                member_digest = h.hexdigest()
        reader.drain()
    except (tarfile.TarError, EOFError, zlib.error, OSError, http.client.HTTPException) as exc:
        raise ProvenanceError(UNAVAILABLE if isinstance(exc, (OSError, http.client.HTTPException)) else UNVERIFIED) from exc
    if seen != 1 or member_digest is None:
        raise ProvenanceError(UNVERIFIED)
    if reader.digest.hexdigest() != asset.digest:
        raise ProvenanceError(UNVERIFIED)
    return member_digest


def fetch_member(transport: _Transport, asset: ReleaseAsset, *, sink: int | None = None) -> str:
    """Download ``asset`` and return its member's sha256 (``read_member``; ``sink`` as there)."""
    try:
        response = transport.open(asset.url, accept="application/octet-stream")
    except (OSError, http.client.HTTPException) as exc:
        raise ProvenanceError(UNAVAILABLE) from exc
    try:
        return read_member(response, asset, sink=sink)
    finally:
        response.close()


def _candidates(transport: _Transport, host: HostPlatform, hint: str | None, rejected: dict):
    """The platform assets to examine, in candidate order (AGYROLL §1.2, PROVFWD-detail §1.2).

    The hint first, when it names a listed stable release; then the listing in order. An asset
    whose archive refused ``UNVERIFIED`` in the last 24 h goes after every asset that has not,
    so an archive that keeps refusing cannot spend every call's budget ahead of untried
    releases. The hinted asset keeps first place after one refusal (a download damaged in
    transit) and goes last at two. Order only: every fetch still costs both budgets, and
    admission is still the member digest.
    """
    def asset_of(release):
        try:
            return release_asset(release, host)
        except ProvenanceError:
            return None  # an unusable release is skipped, as before

    listing, passed, hinted = _stable(transport), [], None
    if hint is not None:
        for release in listing:
            if release.get("tag_name") == hint:
                hinted = asset_of(release)
                break
            passed.append(release)
    hinted_last = hinted is not None and rejected.get(hinted.digest, 0) >= 2
    seen, deferred = set(), []
    if hinted is not None:
        seen.add(hinted.digest)
        if not hinted_last:
            yield hinted
    for release in chain(passed, listing):
        asset = asset_of(release)
        if asset is None or asset.digest in seen:
            continue
        seen.add(asset.digest)
        if rejected.get(asset.digest, 0) >= 1:
            deferred.append(asset)
        else:
            yield asset
    yield from deferred
    if hinted_last:
        yield hinted


def find_provenance(image_sha256: str, *, host: HostPlatform, transport: _Transport | None = None,
                    cached_member=lambda asset: None, remember_member=lambda asset, member: None,
                    hint: str | None = None, budget: int = DOWNLOAD_BUDGET,
                    fetch_times=lambda: (), note_fetch=lambda at: None,
                    rejected=lambda: {}, note_rejected=lambda asset_sha256, at: None,
                    attest=None, now=time.time) -> Provenance:
    """Match ``image_sha256`` against every listed stable release for ``host``.

    ``cached_member``/``remember_member`` are the store's authenticated member-digest cache
    (keyed on the asset digest and runtime identity): a cached member costs nothing, and each
    fetch is remembered before the next candidate, so repeated calls make steady progress.

    Before each uncached fetch: at ``TOTAL_DOWNLOAD_CAP`` or more ``fetch_times()`` inside the
    last ``TOTAL_DOWNLOAD_WINDOW_S`` the call refuses ``DOWNLOAD_CAP_REACHED``; after
    ``budget`` fetches in this call it refuses ``BUDGET_EXHAUSTED``; otherwise ``note_fetch``
    charges the ledger, then the archive is fetched, so a failed or interrupted download is
    still counted. ``note_fetch`` may itself refuse (raise ``ProvenanceError``) when the charge
    finds the ledger full or invalid; nothing is fetched then. A malformed archive (``UNVERIFIED``) is skipped and reported through
    ``note_rejected``; ``UNAVAILABLE`` propagates. ``fetch_times``/``note_fetch`` and
    ``rejected``/``note_rejected`` are the caller's ledger; the defaults keep none.

    On a match, ``attest`` (default ``agy_attestation.attestation_status``) is called once for
    the matched asset and its value recorded. No match after every candidate refuses
    ``UNVERIFIED`` with no reason: the definitive refusal.
    """
    transport = transport or _Transport()
    if attest is None:
        from .agy_attestation import attestation_status as attest
    fetched = 0
    for asset in _candidates(transport, host, hint, dict(rejected() or {})):
        member = cached_member(asset)
        if member is None:
            cutoff = now() - TOTAL_DOWNLOAD_WINDOW_S
            if sum(1 for at in fetch_times() if at > cutoff) >= TOTAL_DOWNLOAD_CAP:
                raise ProvenanceError(UNVERIFIED, DOWNLOAD_CAP_REACHED)
            if fetched >= budget:
                raise ProvenanceError(UNVERIFIED, BUDGET_EXHAUSTED)
            note_fetch(now())
            fetched += 1
            try:
                member = fetch_member(transport, asset)
            except ProvenanceError as exc:
                if str(exc) == UNAVAILABLE:
                    raise
                note_rejected(asset.digest, now())
                continue  # one malformed asset does not hide older releases
            remember_member(asset, member)
        if member == image_sha256:
            return Provenance(image_sha256, host.name, asset, attestation=attest(asset))
    raise ProvenanceError(UNVERIFIED)
