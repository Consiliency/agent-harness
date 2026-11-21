"""Attestation status and the catalog job's second channel for an agy release asset (AGYROLL §1.3, R5).

Nothing here executes anything, and neither answer is an admission criterion:

- ``attestation_status`` records whether GitHub lists an attestation for the asset's digest.
  It never verifies one and never refuses for ``absent``. First use calls it once, for the
  matched asset, so the GitHub API is a dependency of first use: a rate-limited or malformed
  answer refuses ``unavailable``.
- ``second_channel_status`` cross-checks the asset against Google's installer manifest. Only
  the catalog job (the upstream watch) calls it, never per-host first use. ``not_listed``
  says the second channel could say nothing about this version; it is not corroboration.

The transport is this module's own pinned opener. Like ``agy_provenance._Transport`` it uses
``http.client`` (no proxy support), sends no ``Authorization`` header, never reads ``.netrc``,
credential helpers, token or proxy variables, and verifies TLS against the interpreter's
compiled-in trust store (``agy_provenance._trust_context``). Unlike it, it follows no
redirect, and it allows exactly three hosts: the GitHub API, the manifest host and Google's
package host.
"""
from __future__ import annotations

from hashlib import sha256, sha512
import http.client
import json
import posixpath
import re
from urllib.parse import urlsplit

from . import agy_provenance as _provenance
from .agy_provenance import UNAVAILABLE, USER_AGENT, ProvenanceError, ReleaseAsset

ATTESTATION_STATUSES = ("absent", "present_unverified", "not_checked")
SECOND_CHANNEL_STATUSES = ("match", "not_listed", "not_checked")
SECOND_CHANNEL_MISMATCH = "agy_provenance_second_channel_mismatch"

MANIFEST_HOST = "antigravity-cli-auto-updater-974169037036.us-central1.run.app"
MANIFEST_PATH = "/manifests/linux_amd64.json"
MANIFEST_DOWNLOAD_PREFIX = "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
MAX_MANIFEST_BYTES = 262_144
PACKAGE_HOST = "storage.googleapis.com"
ALLOWED_HOSTS = frozenset({_provenance.API_HOST, MANIFEST_HOST, PACKAGE_HOST})
_PACKAGE_PATH_PREFIX = urlsplit(MANIFEST_DOWNLOAD_PREFIX).path
# The only platform Google's installer publishes a manifest for (MANIFEST_PATH).
MANIFEST_PLATFORM = "linux-x64"

_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_SHA512 = re.compile(r"[0-9a-fA-F]{128}")
_CHUNK_BYTES = 1024 * 1024
# What ``_read_json`` returns for its ``absent_status``. JSON ``null`` decodes to ``None``, so
# absence needs a value no document can be.
_ABSENT = object()


def _clean(url) -> bool:
    """ASCII with no space or control character. ``urlsplit`` silently drops tabs and
    newlines, so a URL is checked before it is parsed, never only after."""
    return isinstance(url, str) and url.isascii() and not any(c <= " " or c == "\x7f" for c in url)


class _Opener:
    """https GET to the three allowed hosts: no credentials, no proxy, no redirect.

    ``open`` returns the response for any non-redirect status, so a caller can tell 404 from
    200; every 3xx refuses ``unavailable`` without a second request.
    """

    def __init__(self, *, connection=http.client.HTTPSConnection, context_factory=None, timeout: float = 60):
        self.connection, self.context_factory, self.timeout = connection, context_factory, timeout

    def open(self, url: str, *, accept: str):
        if not _clean(url):
            raise ProvenanceError(UNAVAILABLE)
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise ProvenanceError(UNAVAILABLE) from exc
        if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or port not in (None, 443)
                or parts.username is not None or parts.password is not None):
            raise ProvenanceError(UNAVAILABLE)
        # Looked up when the request is made, so the trust rule is agy_provenance's, always.
        context = (self.context_factory or _provenance._trust_context)()
        conn = self.connection(parts.hostname, 443, context=context, timeout=self.timeout)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        try:
            conn.request("GET", target, headers={"Accept": accept, "User-Agent": USER_AGENT})
            response = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            raise ProvenanceError(UNAVAILABLE) from exc
        if 300 <= response.status < 400:
            response.close()
            conn.close()
            raise ProvenanceError(UNAVAILABLE)
        return response


def _read_json(transport, url: str, *, limit: int, accept: str, absent_status=None):
    """One bounded JSON document (which may be ``None``, for ``null``), or ``_ABSENT`` for
    ``absent_status``; anything else unavailable."""
    try:
        response = transport.open(url, accept=accept)
        try:
            status = response.status
            if absent_status is not None and status == absent_status:
                return _ABSENT
            if status != 200:
                raise ProvenanceError(UNAVAILABLE)
            body = response.read(limit + 1)
        finally:
            response.close()
        if len(body) > limit:
            raise ProvenanceError(UNAVAILABLE)
        return json.loads(body)
    except (OSError, ValueError, RecursionError, http.client.HTTPException) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError(UNAVAILABLE) from exc


def attestation_status(asset: ReleaseAsset, transport=None) -> str:
    """``absent`` or ``present_unverified`` for the asset's archive digest; never verified.

    GitHub answers 404 when it lists no attestation for the digest, and 200 with
    ``{"attestations": [...]}`` when it lists any. An empty list, a non-object, another
    status, an oversized or unparseable body and a network error all refuse ``unavailable``:
    an empty list is not a documented answer, so it is not read as ``absent``.
    """
    transport = transport or _Opener()
    url = f"https://{_provenance.API_HOST}/repos/{_provenance.REPO}/attestations/sha256:{asset.digest}"
    document = _read_json(transport, url, limit=_provenance.MAX_LISTING_BYTES,
                          accept="application/vnd.github+json", absent_status=404)
    if document is _ABSENT:
        return "absent"
    if isinstance(document, dict) and isinstance(document.get("attestations"), list) and document["attestations"]:
        return "present_unverified"
    raise ProvenanceError(UNAVAILABLE)


def _read_manifest(transport) -> dict:
    """Google's installer manifest ``{version, url, sha512}``, validated before any use."""
    manifest = _read_json(transport, f"https://{MANIFEST_HOST}{MANIFEST_PATH}", limit=MAX_MANIFEST_BYTES,
                          accept="application/json")
    if not isinstance(manifest, dict):
        raise ProvenanceError(UNAVAILABLE)
    version, url, digest = manifest.get("version"), manifest.get("url"), manifest.get("sha512")
    if not (isinstance(version, str) and _VERSION.fullmatch(version)
            and isinstance(url, str) and url.startswith(MANIFEST_DOWNLOAD_PREFIX)
            and isinstance(digest, str) and _SHA512.fullmatch(digest)):
        raise ProvenanceError(UNAVAILABLE)
    return {"version": version, "url": _package_target(url), "sha512": digest.lower()}


def _package_target(url: str) -> str:
    """``url`` if the request the opener would make for it stays under the package prefix.

    The prefix alone is not enough: a dot segment, a query or a fragment could point elsewhere
    on the package host, and ``urlsplit`` drops tabs and newlines, so ``.<TAB>.`` passes a raw
    check and is sent as ``..``. So the URL must be clean before parsing, and the EFFECTIVE
    request is checked after it: https to the package host on the default port, no user info,
    query or fragment, and a path under the prefix whose every segment is a plain name (no
    empty, ``.``, ``..``, percent-encoded or backslash segment), so no normalization by the
    server can move it out of the prefix. Anything else refuses ``unavailable``.
    """
    if not _clean(url) or not url.startswith(MANIFEST_DOWNLOAD_PREFIX) or "?" in url or "#" in url:
        raise ProvenanceError(UNAVAILABLE)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ProvenanceError(UNAVAILABLE) from exc
    path = parts.path
    if (parts.scheme != "https" or parts.hostname != PACKAGE_HOST or port is not None
            or parts.username is not None or parts.password is not None or parts.query or parts.fragment
            or not path.startswith(_PACKAGE_PATH_PREFIX) or "%" in path or "\\" in path
            or any(segment in ("", ".", "..") for segment in path[len(_PACKAGE_PATH_PREFIX):].split("/"))
            or posixpath.normpath(path) != path):
        raise ProvenanceError(UNAVAILABLE)
    return url


def _package_digests(transport, url: str) -> tuple[str, str]:
    """(sha512, sha256) of Google's package, hashed while streaming within ``MAX_ARCHIVE_BYTES``.

    The URL is checked again as it will be requested (``_package_target``) before any request."""
    url = _package_target(url)
    try:
        response = transport.open(url, accept="application/octet-stream")
        try:
            if response.status != 200:
                raise ProvenanceError(UNAVAILABLE)
            wide, narrow, size = sha512(), sha256(), 0
            while chunk := response.read(_CHUNK_BYTES):
                size += len(chunk)
                if size > _provenance.MAX_ARCHIVE_BYTES:
                    raise ProvenanceError(UNAVAILABLE)
                wide.update(chunk)
                narrow.update(chunk)
        finally:
            response.close()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError(UNAVAILABLE) from exc
    return wide.hexdigest(), narrow.hexdigest()


def second_channel_status(asset: ReleaseAsset, member_sha256: str, *, host, transport=None) -> str:
    """``match`` or ``not_listed`` for the asset, against Google's installer manifest.

    The comparison basis is the archive (PROVFWD-detail §2.2, measured on 2026-11-20: Google's
    package and the GitHub asset were the same bytes). The manifest publishes only a SHA-512,
    and GitHub only the asset's SHA-256, so the check fetches the package the manifest names,
    requires its SHA-512 to be the manifest's, and compares its SHA-256 with the asset's
    published digest: equal means the manifest's SHA-512 is the GitHub asset's.
    ``member_sha256`` is what the watch fetched; it is already bound to that asset digest by
    ``read_member``, so the archive comparison covers it.

    - A platform other than ``linux-x64`` has no manifest: ``not_listed``, with no request.
    - A manifest for another version, before or after the comparison: ``not_listed``. It
      never reports ``match`` for a version the manifest does not name.
    - An unreachable or malformed manifest, a package that is not the manifest's, or a
      same-version manifest that changes during the check: ``unavailable``.
    - A difference: ``SECOND_CHANNEL_MISMATCH``.
    """
    if host.name != MANIFEST_PLATFORM:
        return "not_listed"
    transport = transport or _Opener()
    manifest = _read_manifest(transport)
    if manifest["version"] != asset.version:
        return "not_listed"
    package_sha512, package_sha256 = _package_digests(transport, manifest["url"])
    if package_sha512 != manifest["sha512"]:
        raise ProvenanceError(UNAVAILABLE)
    same = package_sha256 == asset.digest
    again = _read_manifest(transport)
    if again["version"] != manifest["version"]:
        return "not_listed"
    if again != manifest:
        raise ProvenanceError(UNAVAILABLE)
    if not same:
        raise ProvenanceError(SECOND_CHANNEL_MISMATCH)
    return "match"
