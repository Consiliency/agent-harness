"""The grok release catalog, its gate file and the offline tree invariant (GROKROLL §1,
§2.4, §2.5).

``data/grok_releases.json`` maps a grok version to the digest of its native binary. It
ships empty and stays empty until the gate file ``data/grok_catalog_gate.json`` is attested
by the owner (§2.5). Every loader rule is fail-closed: one bad entry voids the file.

``check_tree`` is the offline invariant over the three shipped files (the gate, the release
catalog and the tool-surface catalog). It takes an explicit data directory, so it can run on
a pull request's head tree and on fixtures as well as on the installed package data.

``cryptography`` is imported lazily, only by :func:`verify_entry_signature`; the loader and
the status query need it not.
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import os
import re
import stat
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping

RELEASES_NAME = "grok_releases.json"
GATE_NAME = "grok_catalog_gate.json"
SURFACES_NAME = "grok_tool_surfaces.json"
#: The package-data directory, relative to a repository checkout.
DATA_RELATIVE = "phase-loop-runtime/src/phase_loop_runtime/data"

RELEASE_CATALOG_SCHEMA = "grok_release_catalog.v1"
GATE_SCHEMA = "grok_catalog_gate.v1"
PLATFORM = "linux-x64"
PACKAGE = "@xai-official/grok-linux-x64"
MEMBER = "package/bin/grok.br"

CATALOG_MAX_BYTES = 256 * 1024
GATE_MAX_BYTES = 4096
MAX_RELEASES = 24
RELEASE_KEEP = 12
SURFACE_KEEP = 8
MAX_TARBALL_BYTES = 128 * 1024 * 1024
MAX_BINARY_BYTES = 512 * 1024 * 1024

#: The registry signing keys an entry's stored signature may verify under (§2.2 step 3):
#: key id (the registry's label, matched as a string) to SubjectPublicKeyInfo, base64 DER.
#: Changing this constant is a reviewed code change.
REGISTRY_KEYS: Mapping[str, str] = {
    "SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U":
        "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEY6Ya7W++7aUPzvMTrezH6Ycx3c+HOKYCcNGybJZSCJq/fd7Q"
        "a8uuAKtdIkUQtQiEKERhAmE5lMMJhP8OkDOa2g==",
}

_ENTRY_KEYS = frozenset({"version", "package", "tarball_integrity", "registry_keyid",
                         "registry_signature", "member", "binary_sha256", "binary_bytes",
                         "pinned"})
_GATE_KEYS = frozenset({"schema", "attested", "ruleset_scope", "ruleset_id", "workflow_ref",
                        "attested_at"})
_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_INTEGRITY = re.compile(r"sha512-[A-Za-z0-9+/]{86}==")
_SIGNATURE_MAX = 256
_WORKFLOW_REF = re.compile(r"refs/(heads|tags)/([A-Za-z0-9._/-]{1,200})")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_VERSION_TOKEN = re.compile(r"(?<![0-9.])([0-9]+)\.([0-9]+)\.([0-9]+)(?![0-9.])")


class CatalogRefused(ValueError):
    """A catalog or gate file broke one rule. ``code`` is a closed slug."""

    def __init__(self, code: str = "grok_catalog_invalid") -> None:
        super().__init__(code)
        self.code = code


class CatalogDependencyMissing(RuntimeError):
    """The ``grok-catalog`` extra is not installed (``grok_catalog_dependency_missing``)."""

    code = "grok_catalog_dependency_missing"


def _require(condition: bool, code: str = "grok_catalog_invalid") -> None:
    if not condition:
        raise CatalogRefused(code)


def _strict_object(pairs):
    keys = [key for key, _value in pairs]
    _require(len(keys) == len(set(keys)))
    return dict(pairs)


def _no_constant(_name: str):
    raise CatalogRefused()


def _loads(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                          parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CatalogRefused() from exc


def version_key(version: str) -> tuple[int, int, int]:
    """A canonical ``MAJOR.MINOR.PATCH`` as an integer triple; the only order (§1)."""
    match = _VERSION.fullmatch(version) if type(version) is str else None
    _require(match is not None)
    assert match is not None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_version(value: object) -> bool:
    return type(value) is str and _VERSION.fullmatch(value) is not None


def is_digest(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _integrity_ok(value: object) -> bool:
    if type(value) is not str or _INTEGRITY.fullmatch(value) is None:
        return False
    try:
        return len(base64.b64decode(value[len("sha512-"):], validate=True)) == 64
    except (binascii.Error, ValueError):
        return False


def _check_entry(entry: object) -> None:
    _require(type(entry) is dict and set(entry) == _ENTRY_KEYS)
    assert isinstance(entry, dict)
    _require(is_version(entry["version"]))
    _require(entry["package"] == PACKAGE and entry["member"] == MEMBER)
    _require(_integrity_ok(entry["tarball_integrity"]))
    _require(type(entry["registry_keyid"]) is str and entry["registry_keyid"] in REGISTRY_KEYS)
    signature = entry["registry_signature"]
    _require(type(signature) is str and 0 < len(signature) <= _SIGNATURE_MAX)
    _require(is_digest(entry["binary_sha256"]))
    size = entry["binary_bytes"]
    _require(type(size) is int and 1 <= size <= MAX_BINARY_BYTES)
    _require(type(entry["pinned"]) is bool)


@dataclass(frozen=True)
class ReleaseCatalog:
    """A loaded ``grok_release_catalog.v1``: its entries in ascending version order."""

    platform: str
    releases: tuple[Mapping[str, Any], ...]

    def by_version(self, version: str) -> Mapping[str, Any] | None:
        return next((entry for entry in self.releases if entry["version"] == version), None)

    def by_digest(self, digest: str) -> Mapping[str, Any] | None:
        return next((entry for entry in self.releases if entry["binary_sha256"] == digest), None)

    def newest_first(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(reversed(self.releases))


def parse_releases(raw: bytes) -> ReleaseCatalog:
    """The release catalog in ``raw``, or :class:`CatalogRefused`. One bad entry voids the
    whole file (§1)."""
    _require(type(raw) is bytes and len(raw) <= CATALOG_MAX_BYTES)
    document = _loads(raw)
    _require(type(document) is dict and set(document) == {"schema", "platform", "releases"})
    assert isinstance(document, dict)
    _require(document["schema"] == RELEASE_CATALOG_SCHEMA and document["platform"] == PLATFORM)
    releases = document["releases"]
    _require(type(releases) is list)
    _require(len(releases) <= MAX_RELEASES, "grok_catalog_too_many_releases")
    for entry in releases:
        _check_entry(entry)
    versions = [entry["version"] for entry in releases]
    digests = [entry["binary_sha256"] for entry in releases]
    _require(len(set(versions)) == len(versions) and len(set(digests)) == len(digests))
    keys = [version_key(version) for version in versions]
    _require(keys == sorted(keys))
    return ReleaseCatalog(platform=document["platform"], releases=tuple(releases))


# Native Windows has none of these flags (nor ``dir_fd``): ``None`` makes every open fail closed.
if os.name != "nt":
    _DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    _FILE_FLAGS = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                   | getattr(os, "O_NOCTTY", 0))
else:
    _DIR_FLAGS = _FILE_FLAGS = None

DataPath = str | os.PathLike[str]


def _read_at(directory: int, name: str, limit: int) -> bytes:
    """``name`` in the open ``directory``: a regular file, opened without following a link
    and without blocking, read through that one descriptor with a bound."""
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CatalogRefused()
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(descriptor, limit + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _open_below(anchor: DataPath, relative: str) -> int:
    """The directory ``relative`` below ``anchor``, each component opened without following
    a link. ``anchor`` is the caller's trust root (a checkout, or the installed package)."""
    parts = [part for part in relative.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        raise CatalogRefused()
    descriptor = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts:
            child = os.open(part, _DIR_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_package_data(name: str, limit: int) -> bytes:
    """A package-data file. A filesystem-backed package is read as any tree is: the ``data``
    directory and the file must not be links, and the file must be regular. A package with
    no filesystem path (a zip import) is read through ``importlib.resources``."""
    package = resources.files("phase_loop_runtime")
    if isinstance(package, Path):
        directory = _open_below(package, "data")
        try:
            return _read_at(directory, name, limit)
        finally:
            os.close(directory)
    with package.joinpath("data", name).open("rb") as source:  # pragma: no cover - zip
        return source.read(limit + 1)


def _locate(data_dir: DataPath | None, anchor: DataPath | None) -> tuple[DataPath, str]:
    """``(anchor, relative)`` for an explicit tree. With only ``data_dir``, the anchor is
    its parent, so a linked data directory is refused; with ``anchor``, every component
    from it down is checked."""
    if anchor is None:
        assert data_dir is not None
        absolute = os.path.abspath(os.fspath(data_dir))
        return os.path.dirname(absolute), os.path.basename(absolute)
    if data_dir is None:
        return anchor, DATA_RELATIVE
    relative = os.path.relpath(os.path.abspath(os.fspath(data_dir)),
                               os.path.abspath(os.fspath(anchor)))
    if relative == ".." or relative.startswith("../") or relative == ".":
        raise CatalogRefused()
    return anchor, relative


def read_data(name: str, limit: int, data_dir: DataPath | None = None, *,
              anchor: DataPath | None = None) -> bytes:
    """A data file: from the explicit tree (``data_dir`` and/or ``anchor``) when given, else
    the installed package data."""
    if data_dir is None and anchor is None:
        return _read_package_data(name, limit)
    root, relative = _locate(data_dir, anchor)
    directory = _open_below(root, relative)
    try:
        return _read_at(directory, name, limit)
    finally:
        os.close(directory)


def load_releases(data_dir: DataPath | None = None, *,
                  anchor: DataPath | None = None) -> ReleaseCatalog | None:
    """The release catalog, or ``None`` on any refusal (§1: reported ``unavailable``)."""
    try:
        return parse_releases(read_data(RELEASES_NAME, CATALOG_MAX_BYTES, data_dir,
                                        anchor=anchor))
    except (OSError, ValueError, TypeError, RecursionError):
        return None


# ------------------------------------------------------------------------------ the gate

@dataclass(frozen=True)
class Gate:
    attested: bool
    ruleset_scope: str | None
    ruleset_id: int | None
    workflow_ref: str | None
    attested_at: str | None


def workflow_ref_ok(ref: object) -> bool:
    """A full branch or tag ref that ``git check-ref-format`` accepts: ``refs/heads/`` or
    ``refs/tags/``, then components that are non-empty, do not start with ``.``, do not end
    with ``.lock``, with no ``..`` or ``@{`` and no trailing ``.`` or ``/``. The character
    set already excludes space, control characters and ``~^:?*[\\``."""
    match = _WORKFLOW_REF.fullmatch(ref) if type(ref) is str else None
    if match is None:
        return False
    assert isinstance(ref, str)
    components = match.group(2).split("/")
    return (all(part and not part.startswith(".") and not part.endswith(".lock")
                for part in components)
            and ".." not in ref and "@{" not in ref and not ref.endswith("."))


def utc_time_ok(value: object) -> bool:
    """``YYYY-MM-DDTHH:MM:SSZ`` naming a real calendar time."""
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return False
    try:
        _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def parse_gate(raw: bytes) -> Gate:
    """The gate file in ``raw`` if well formed (§2.5), else :class:`CatalogRefused`."""
    _require(type(raw) is bytes and len(raw) <= GATE_MAX_BYTES, "grok_catalog_gate_invalid")
    try:
        document = _loads(raw)
    except CatalogRefused as exc:
        raise CatalogRefused("grok_catalog_gate_invalid") from exc
    ok = type(document) is dict and set(document) == _GATE_KEYS
    if ok:
        assert isinstance(document, dict)
        fields = (document["ruleset_scope"], document["ruleset_id"], document["workflow_ref"],
                  document["attested_at"])
        ok = document["schema"] == GATE_SCHEMA and type(document["attested"]) is bool
        if ok and document["attested"] is False:
            ok = all(value is None for value in fields)
        elif ok:
            scope, ruleset, ref, at = fields
            ok = (scope in ("organization", "enterprise")
                  and type(ruleset) is int and ruleset > 0
                  and workflow_ref_ok(ref) and utc_time_ok(at))
    _require(ok, "grok_catalog_gate_invalid")
    assert isinstance(document, dict)
    return Gate(attested=document["attested"], ruleset_scope=document["ruleset_scope"],
                ruleset_id=document["ruleset_id"], workflow_ref=document["workflow_ref"],
                attested_at=document["attested_at"])


def load_gate(data_dir: DataPath | None = None, *, anchor: DataPath | None = None) -> Gate | None:
    """The gate file, or ``None`` when it is missing or malformed."""
    try:
        return parse_gate(read_data(GATE_NAME, GATE_MAX_BYTES, data_dir, anchor=anchor))
    except (OSError, ValueError, TypeError, RecursionError):
        return None


GATE_STATES = ("attested", "unattested", "invalid")


def gate_state(data_dir: DataPath | None = None, *, anchor: DataPath | None = None) -> str:
    """``attested``, ``unattested`` or ``invalid`` (missing, linked, non-regular or
    malformed). Only ``attested`` establishes release-catalog membership (GROKROLL E1)."""
    gate = load_gate(data_dir, anchor=anchor)
    if gate is None:
        return "invalid"
    return "attested" if gate.attested else "unattested"


# ------------------------------------------------------------------- the signature check

def verify_entry_signature(entry: Mapping[str, Any]) -> bool:
    """Does ``entry``'s stored registry signature verify, ECDSA P-256 over SHA-256, on the
    UTF-8 bytes ``<package>@<version>:<tarball_integrity>`` under the key ``REGISTRY_KEYS``
    names for its key id (§2.2 step 3)? A key id the constant lacks is unknown: ``False``.

    Raises :class:`CatalogDependencyMissing` without the ``grok-catalog`` extra."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import load_der_public_key
    except ImportError as exc:
        raise CatalogDependencyMissing(CatalogDependencyMissing.code) from exc
    try:
        key_text = REGISTRY_KEYS.get(entry["registry_keyid"]) if type(
            entry.get("registry_keyid")) is str else None
        if key_text is None:
            return False
        name, version, integrity = entry["package"], entry["version"], entry["tarball_integrity"]
        if not all(type(value) is str for value in (name, version, integrity)):
            return False
        signature = base64.b64decode(entry["registry_signature"], validate=True)
        key = load_der_public_key(base64.b64decode(key_text, validate=True))
        if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
            return False
        key.verify(signature, f"{name}@{version}:{integrity}".encode("utf-8"),
                   ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, KeyError, TypeError, ValueError, binascii.Error,
            UnicodeEncodeError):
        return False
    return True


# ----------------------------------------------------------------------------- aging

def aging(catalog: ReleaseCatalog, surfaced: Iterable[str] = ()) -> tuple[Mapping[str, Any], ...]:
    """The entries release-catalog aging keeps (§5.2), in catalog order: every entry with a
    surface (its ``binary_sha256`` in ``surfaced``), every ``pinned`` entry, and the newest
    ``RELEASE_KEEP``. The rest may be pruned; nothing here prunes."""
    surfaced = frozenset(surfaced)
    newest = {entry["version"] for entry in catalog.newest_first()[:RELEASE_KEEP]}
    return tuple(entry for entry in catalog.releases
                 if entry["pinned"] or entry["binary_sha256"] in surfaced
                 or entry["version"] in newest)


# ------------------------------------------------------------------ the tree invariant

@dataclass(frozen=True)
class TreeCheck:
    """The result of :func:`check_tree`: ``step`` (1 to 5) and ``code`` name the first
    failing step, both ``None`` when the tree holds."""

    passed: bool
    step: int | None = None
    code: str | None = None


def surface_version_token(version_text: object) -> str | None:
    """The single ``x.y.z`` token in a surface's ``version`` text, else ``None``."""
    if type(version_text) is not str:
        return None
    tokens = {".".join(match.groups()) for match in _VERSION_TOKEN.finditer(version_text)}
    return tokens.pop() if len(tokens) == 1 else None


def check_tree(data_dir: DataPath | None = None, *, anchor: DataPath | None = None) -> TreeCheck:
    """The offline tree invariant (§2.4) over the gate file, the release catalog and the
    surface catalog in an explicit tree, else the installed package data. No network.

    ``anchor`` is a checkout root: the files are read from ``DATA_RELATIVE`` below it (or
    from ``data_dir`` below it), with no linked component from the anchor down. With only
    ``data_dir``, the data directory itself must not be a link.

    1. the gate file is well formed;
    2. the release catalog loads, which includes the ``MAX_RELEASES`` bound;
    3. if the gate is unattested, the release catalog is empty;
    4. every entry's stored signature verifies under ``REGISTRY_KEYS``;
    5. if the gate is attested, §1 parity holds for every surface.
    """
    try:
        gate = parse_gate(read_data(GATE_NAME, GATE_MAX_BYTES, data_dir, anchor=anchor))
    except (OSError, ValueError, TypeError, RecursionError):
        return TreeCheck(False, 1, "grok_catalog_gate_invalid")
    try:
        catalog = parse_releases(read_data(RELEASES_NAME, CATALOG_MAX_BYTES, data_dir,
                                           anchor=anchor))
    except CatalogRefused as exc:
        return TreeCheck(False, 2, exc.code)
    except (OSError, ValueError, TypeError, RecursionError):
        return TreeCheck(False, 2, "grok_catalog_invalid")
    if not gate.attested and catalog.releases:
        return TreeCheck(False, 3, "grok_catalog_unattested_not_empty")
    if not all(verify_entry_signature(entry) for entry in catalog.releases):
        return TreeCheck(False, 4, "grok_release_unverified")
    if gate.attested:
        from .. import grok_tool_surface as surfaces

        try:
            shipped = surfaces.parse_catalog(
                read_data(SURFACES_NAME, surfaces.CATALOG_MAX_BYTES, data_dir, anchor=anchor))
        except (OSError, ValueError, TypeError, RecursionError):
            return TreeCheck(False, 5, "grok_surface_catalog_invalid")
        for digest, surface in shipped.surfaces.items():
            member = catalog.by_digest(digest)
            if member is None or surface_version_token(surface["version"]) != member["version"]:
                return TreeCheck(False, 5, "grok_surface_without_member")
    return TreeCheck(True)


def repository_data_dir(tree: str | os.PathLike[str]) -> Path:
    """The package-data directory of a repository checkout at ``tree``."""
    return Path(tree) / DATA_RELATIVE
