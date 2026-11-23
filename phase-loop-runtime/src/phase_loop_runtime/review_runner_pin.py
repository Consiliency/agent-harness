"""Review-runner image pin record (``review_runner_pin.v1``, RRIMAGE contract §2).

A pure validator for the metadata-only record that binds the review-runner image to its
source, its helper and, once ai-stack's pull receipt is verified, its pushed reference.

- :func:`load_pin_record` parses a record file.
- :func:`validate_pin_record` applies rules P1–P10 against a checkout and returns a
  :class:`PinVerdict`. P4 is strict unless ``allow_stale_marker=True`` and the sibling stale
  marker names this exact record (§2.1).
- :func:`assemble_built_record` reads a local OCI layout and returns the ``built`` record with
  the raw manifest and config bytes to commit beside it (§3.4).
- :func:`apply_receipt` promotes a ``built`` record to ``pinned`` from a verified receipt.

Every refusal is a :class:`PinRecordError` carrying one closed code, raised ``from None``.
Its message names the rule and the field, never a record value. Nothing here runs a
subprocess or makes a network call.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterator, Mapping

import jsonschema
import rfc8785

SCHEMA_ID = "review_runner_pin.v1"
SCHEMA_RESOURCE = "contracts/placement/review-runner-pin-v1.schema.json"
STALE_MARKER_SCHEMA = "review_runner_pin_stale.v1"
STALE_MARKER_PATH = "plans/evidence/review-runner/pin-record.stale.json"
PIN_JSON_PATH = "phase-loop-runtime/tests/data/landlock-exec/PIN.json"

PIN_CODES = frozenset({
    "pin_schema_invalid",
    "pin_reference_mismatch",
    "pin_index_refused",
    "pin_containerfile_stale",
    "pin_helper_mismatch",
    "pin_receipt_mismatch",
    "pin_credential_sentinel",
    "pin_digest_mismatch",
    "pin_reproducibility_inconsistent",
    "pin_source_mismatch",
    "pin_not_pinned",
})

MANIFEST_MEDIA_TYPES = frozenset({
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
})
INDEX_MEDIA_TYPES = frozenset({
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
})
REVISION_LABEL = "org.opencontainers.image.revision"
CONTAINERFILE_LABEL = "dev.consiliency.review-runner.containerfile-sha256"

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SUFFIX = re.compile(r"@sha256:[0-9a-f]{64}$")
_SENTINELS = ("ghp_", "gho_", "ghs_", "github_pat_", "glpat-", "bearer ", "basic ",
              '"auths"', "password", "token", "secret")
_USERINFO = re.compile(r"(?:^|://)[^\s/@:]+:[^\s/@]+@(?!sha256:)")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{40,}")
_HELPER_HASH_LINE = re.compile(r"echo\s+'([0-9a-f]{64})\s+/landlock-exec'\s*\|\s*sha256sum\s+-c")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class PinRecordError(ValueError):
    """A closed pin-record refusal. ``str()`` names the rule, the code and the field only."""

    def __init__(self, code: str, rule: str, field: str = "") -> None:
        if code not in PIN_CODES:
            code = "pin_schema_invalid"
        self.code = code
        self.rule = rule
        self.field = field or "<record>"
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.rule} {self.code}: {self.field}"


@dataclass(frozen=True)
class PinVerdict:
    """The outcome of :func:`validate_pin_record`.

    ``status`` is ``built``, ``pinned`` or ``stale``. Consumers accept only ``pinned``,
    reached with the default strict P4; ``stale`` means P4 failed but the stale marker named
    this record, and no consumer accepts it.
    """

    status: str
    record_status: str
    record_sha256: str

    @property
    def pinned(self) -> bool:
        return self.status == "pinned"

    def require_pinned(self) -> None:
        if self.status != "pinned":
            raise PinRecordError("pin_not_pinned", "status", "status")


@dataclass(frozen=True)
class AssembledRecord:
    """A ``built`` record and the exact bytes to commit at its manifest and config paths."""

    record: dict[str, Any]
    manifest_bytes: bytes
    config_bytes: bytes


# -- schema ----------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def schema_bytes() -> bytes:
    """The packaged ``review_runner_pin.v1`` schema, exactly as shipped."""
    try:
        return resources.files(__package__).joinpath(SCHEMA_RESOURCE).read_bytes()
    except (OSError, ValueError):
        raise PinRecordError("pin_schema_invalid", "P1", "schema") from None


@lru_cache(maxsize=1)
def _schema() -> Mapping[str, Any]:
    return json.loads(schema_bytes().decode("utf-8"))


def _strict_integer(_checker: object, instance: object) -> bool:
    return isinstance(instance, int) and not isinstance(instance, bool)


@lru_cache(maxsize=1)
def _validator() -> Any:
    base = jsonschema.Draft202012Validator
    checker = base.TYPE_CHECKER.redefine("integer", _strict_integer)
    return jsonschema.validators.extend(base, type_checker=checker)(_schema())


@lru_cache(maxsize=1)
def _digest_fields() -> Mapping[tuple[str, ...], str]:
    """Paths of the §2 digest fields: ``full`` for digest/hex64/commit, ``suffix`` for refs."""
    schema = _schema()
    defs = schema.get("$defs", {})
    found: dict[tuple[str, ...], str] = {}

    def walk(node: Any, path: tuple[str, ...], depth: int) -> None:
        if not isinstance(node, Mapping) or depth > 32:
            return
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref[len("#/$defs/"):]
            if name in {"digest", "hex64", "commit"}:
                found[path] = "full"
            elif name == "pinned_reference":
                found.setdefault(path, "suffix")
            walk(defs.get(name), path, depth + 1)
        for key in ("oneOf", "anyOf", "allOf"):
            for branch in node.get(key, ()) or ():
                walk(branch, path, depth + 1)
        for name, child in (node.get("properties") or {}).items():
            walk(child, path + (name,), depth + 1)
        if "items" in node:
            walk(node["items"], path + ("*",), depth + 1)

    walk(schema, (), 0)
    return found


# -- helpers ---------------------------------------------------------------------------------

def _fail(code: str, rule: str, field: str = "") -> PinRecordError:
    return PinRecordError(code, rule, field)


def _field(path: Any) -> str:
    return ".".join(str(part) for part in path) or "<record>"


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-finite number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _parse_json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path) -> bytes:
    """Read a regular file without following a final symlink."""
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("not a regular file")
    with open(path, "rb") as stream:
        return stream.read()


def record_sha256(record: Mapping[str, Any]) -> str:
    """sha256 of the record's RFC 8785 canonical bytes; the stale marker names this value."""
    try:
        return _sha256(rfc8785.dumps(record))
    except Exception:  # noqa: BLE001 - any encoding failure is a schema failure
        raise _fail("pin_schema_invalid", "P1") from None


def _timestamp(value: str, field: str) -> datetime:
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise _fail("pin_schema_invalid", "P1", field) from None


def _hex(digest: str) -> str:
    match = _DIGEST.match(digest) if isinstance(digest, str) else None
    if match is None:
        raise _fail("pin_digest_mismatch", "P9", "digest")
    return match.group(1)


# -- the record-only rules (P1–P3, P6–P8, P10) ------------------------------------------------

def _check_p3_media_types(record: Any) -> None:
    if not isinstance(record, Mapping):
        return
    for section, key in (("artifact", "manifest_media_type"), ("receipt", "raw_manifest_media_type")):
        value = record.get(section)
        if isinstance(value, Mapping) and value.get(key) in INDEX_MEDIA_TYPES:
            raise _fail("pin_index_refused", "P3", f"{section}.{key}")


def _check_p1_schema(record: Any) -> None:
    if not isinstance(record, Mapping):
        raise _fail("pin_schema_invalid", "P1")
    try:
        error = jsonschema.exceptions.best_match(_validator().iter_errors(record))
    except Exception:  # noqa: BLE001 - a validator crash is still a schema refusal
        raise _fail("pin_schema_invalid", "P1") from None
    if error is not None:
        raise _fail("pin_schema_invalid", "P1", _field(error.absolute_path))


def _strings(value: Any, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], str, bool]]:
    """Yield ``(path, text, is_key)`` for every key and string value."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield path + (str(key),), str(key), True
            yield from _strings(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, path + (str(index),))
    elif isinstance(value, str):
        yield path, value, False


def _schema_path(path: tuple[str, ...]) -> tuple[str, ...]:
    return tuple("*" if part.isdigit() else part for part in path)


def _check_p7_sentinels(record: Mapping[str, Any]) -> None:
    exempt = _digest_fields()
    for path, text, is_key in _strings(record, ()):
        lowered = text.lower()
        if any(sentinel in lowered for sentinel in _SENTINELS) or _USERINFO.search(text):
            raise _fail("pin_credential_sentinel", "P7", _field(path))
        kind = None if is_key else exempt.get(_schema_path(path))
        if kind == "full":
            continue
        probe = _SUFFIX.sub("", text) if kind == "suffix" else text
        if _BASE64_RUN.search(probe):
            raise _fail("pin_credential_sentinel", "P7", _field(path))


def _check_p2_reference(record: Mapping[str, Any]) -> None:
    image = record.get("image")
    if image is None:
        return
    expected = f"{image['registry']}/{image['repository']}@{record['artifact']['manifest_digest']}"
    if image["reference"] != expected:
        raise _fail("pin_reference_mismatch", "P2", "image.reference")


def _check_p10_reproducibility(record: Mapping[str, Any]) -> None:
    build = record["build"]
    rep = build["reproduced"]
    field = "build.reproduced"
    if not rep["attempted"]:
        if (rep["second_manifest_digest"] is not None or rep["equal"] is not None
                or rep["differing_layers"] or rep["deferred_finding"] is not None):
            raise _fail("pin_reproducibility_inconsistent", "P10", field)
        return
    if rep["second_manifest_digest"] is None or rep["equal"] is None:
        raise _fail("pin_reproducibility_inconsistent", "P10", field)
    if rep["equal"] != (rep["second_manifest_digest"] == build["first_manifest_digest"]):
        raise _fail("pin_reproducibility_inconsistent", "P10", f"{field}.equal")
    if rep["equal"]:
        if rep["differing_layers"] or rep["deferred_finding"] is not None:
            raise _fail("pin_reproducibility_inconsistent", "P10", field)
    elif not rep["differing_layers"] or rep["deferred_finding"] is None:
        raise _fail("pin_reproducibility_inconsistent", "P10", field)


def _check_p6_receipt(record: Mapping[str, Any]) -> None:
    receipt = record.get("receipt")
    if record["status"] != "pinned":
        return
    artifact, platform = record["artifact"], record["platform"]
    manifest_digest = artifact["manifest_digest"]
    expected = {
        "registry_manifest_digest": manifest_digest,
        "docker_content_digest": manifest_digest,
        "raw_manifest_sha256": _hex(manifest_digest),
        "raw_manifest_media_type": artifact["manifest_media_type"],
        "config_digest": platform["config_digest"],
        "helper_sha256": record["helper"]["sha256"],
        "os": platform["os"],
        "architecture": platform["architecture"],
        "input_archive_sha256": artifact["oci_archive_sha256"],
        "container_state": "created",
        "started_at_zero": True,
        "entrypoint_started": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value or type(receipt.get(key)) is not type(value):
            raise _fail("pin_receipt_mismatch", "P6", f"receipt.{key}")


def _check_p8_order(record: Mapping[str, Any]) -> None:
    recorded = _timestamp(record["recorded_at"], "recorded_at")
    receipt = record.get("receipt")
    if record["status"] != "pinned":
        return
    pulled = _timestamp(receipt["pulled_at"], "receipt.pulled_at")
    if recorded < pulled:
        raise _fail("pin_receipt_mismatch", "P8", "recorded_at")


def _check_record_only(record: Any) -> None:
    _check_p3_media_types(record)
    _check_p1_schema(record)
    _check_p7_sentinels(record)
    _check_p2_reference(record)
    _check_p10_reproducibility(record)
    _check_p6_receipt(record)
    _check_p8_order(record)


# -- P9: the committed manifest and config bytes ---------------------------------------------

def _check_p9_bytes(record: Mapping[str, Any], manifest_bytes: bytes, config_bytes: bytes) -> None:
    artifact, platform, source = record["artifact"], record["platform"], record["source"]
    manifest_digest = artifact["manifest_digest"]
    if record["build"]["first_manifest_digest"] != manifest_digest:
        raise _fail("pin_digest_mismatch", "P9", "build.first_manifest_digest")
    if _sha256(manifest_bytes) != _hex(manifest_digest):
        raise _fail("pin_digest_mismatch", "P9", "artifact.manifest_digest")
    if len(manifest_bytes) != artifact["manifest_size"]:
        raise _fail("pin_digest_mismatch", "P9", "artifact.manifest_size")
    try:
        manifest = _parse_json(manifest_bytes)
    except (UnicodeDecodeError, ValueError):
        raise _fail("pin_digest_mismatch", "P9", "artifact.manifest_path") from None
    if not isinstance(manifest, Mapping):
        raise _fail("pin_digest_mismatch", "P9", "artifact.manifest_path")
    if manifest.get("mediaType") in INDEX_MEDIA_TYPES or "manifests" in manifest:
        raise _fail("pin_index_refused", "P9", "artifact.manifest_path")
    if manifest.get("mediaType") != artifact["manifest_media_type"]:
        raise _fail("pin_digest_mismatch", "P9", "artifact.manifest_media_type")
    descriptor = manifest.get("config")
    if not isinstance(descriptor, Mapping) or descriptor.get("digest") != platform["config_digest"]:
        raise _fail("pin_digest_mismatch", "P9", "platform.config_digest")
    if _sha256(config_bytes) != _hex(platform["config_digest"]):
        raise _fail("pin_digest_mismatch", "P9", "artifact.config_path")
    if "size" in descriptor and descriptor["size"] != len(config_bytes):
        raise _fail("pin_digest_mismatch", "P9", "artifact.config_path")
    try:
        config = _parse_json(config_bytes)
    except (UnicodeDecodeError, ValueError):
        raise _fail("pin_digest_mismatch", "P9", "artifact.config_path") from None
    if not isinstance(config, Mapping):
        raise _fail("pin_digest_mismatch", "P9", "artifact.config_path")
    for key in ("os", "architecture"):
        if config.get(key) != platform[key]:
            raise _fail("pin_digest_mismatch", "P9", f"platform.{key}")
    inner = config.get("config")
    labels = inner.get("Labels") if isinstance(inner, Mapping) else None
    if not isinstance(labels, Mapping):
        raise _fail("pin_source_mismatch", "P9", "source")
    if labels.get(REVISION_LABEL) != source["commit"]:
        raise _fail("pin_source_mismatch", "P9", "source.commit")
    if labels.get(CONTAINERFILE_LABEL) != source["containerfile_sha256"]:
        raise _fail("pin_source_mismatch", "P9", "source.containerfile_sha256")


def _committed_bytes(repo_root: Path, record: Mapping[str, Any]) -> tuple[bytes, bytes]:
    artifact = record["artifact"]
    out = []
    for key in ("manifest_path", "config_path"):
        try:
            out.append(_read_regular(repo_root / artifact[key]))
        except OSError:
            raise _fail("pin_digest_mismatch", "P9", f"artifact.{key}") from None
    return out[0], out[1]


# -- P5: the helper ---------------------------------------------------------------------------

def _copy_destination(containerfile: str) -> str | None:
    for line in containerfile.splitlines():
        tokens = line.split()
        if len(tokens) < 3 or tokens[0].upper() != "COPY" or "--from=landlock" not in tokens:
            continue
        paths = [token for token in tokens[1:] if not token.startswith("--")]
        if len(paths) == 2 and paths[0] == "/landlock-exec":
            return paths[1]
    return None


def _check_p5_helper(record: Mapping[str, Any], repo_root: Path, containerfile: bytes) -> None:
    helper = record["helper"]
    try:
        text = containerfile.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail("pin_helper_mismatch", "P5", "source.containerfile_path") from None
    lines = set(_HELPER_HASH_LINE.findall(text))
    if lines != {helper["sha256"]}:
        raise _fail("pin_helper_mismatch", "P5", "helper.sha256")
    try:
        pin = _parse_json(_read_regular(repo_root / PIN_JSON_PATH))
    except (OSError, UnicodeDecodeError, ValueError):
        raise _fail("pin_helper_mismatch", "P5", "helper") from None
    if not isinstance(pin, Mapping) or pin.get("helper_sha256") != helper["sha256"]:
        raise _fail("pin_helper_mismatch", "P5", "helper.sha256")
    if pin.get("commit") != helper["source_commit"]:
        raise _fail("pin_helper_mismatch", "P5", "helper.source_commit")
    if _copy_destination(text) != helper["path"]:
        raise _fail("pin_helper_mismatch", "P5", "helper.path")


# -- P4 and the stale marker (§2.1) -----------------------------------------------------------

def _stale_marker_names(repo_root: Path, digest: str) -> bool:
    try:
        marker = _parse_json(_read_regular(repo_root / STALE_MARKER_PATH))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return (isinstance(marker, Mapping)
            and set(marker) == {"schema", "record_sha256", "reason"}
            and marker["schema"] == STALE_MARKER_SCHEMA
            and isinstance(marker["record_sha256"], str)
            and _HEX64.match(marker["record_sha256"]) is not None
            and marker["record_sha256"] == digest
            and isinstance(marker["reason"], str) and marker["reason"].strip() != "")


# -- public API -------------------------------------------------------------------------------

def load_pin_record(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Parse a record file: strict JSON, unique keys, a top-level object."""
    try:
        value = _parse_json(_read_regular(Path(path)))
    except (OSError, UnicodeDecodeError, ValueError):
        raise _fail("pin_schema_invalid", "P1") from None
    if not isinstance(value, dict):
        raise _fail("pin_schema_invalid", "P1")
    return value


def validate_pin_record(record: Mapping[str, Any], repo_root: str | os.PathLike[str], *,
                        allow_stale_marker: bool = False) -> PinVerdict:
    """Apply P1–P10 to ``record`` against the checkout at ``repo_root``.

    P4 is strict by default. With ``allow_stale_marker=True``, a P4 mismatch yields a
    ``stale`` verdict only when ``plans/evidence/review-runner/pin-record.stale.json`` names
    this record's :func:`record_sha256`; every other rule still applies.
    """
    root = Path(repo_root)
    _check_record_only(record)
    manifest_bytes, config_bytes = _committed_bytes(root, record)
    _check_p9_bytes(record, manifest_bytes, config_bytes)
    source = record["source"]
    try:
        containerfile = _read_regular(root / source["containerfile_path"])
    except OSError:
        raise _fail("pin_containerfile_stale", "P4", "source.containerfile_path") from None
    _check_p5_helper(record, root, containerfile)
    digest = record_sha256(record)
    status = record["status"]
    if _sha256(containerfile) != source["containerfile_sha256"]:
        if not (allow_stale_marker and _stale_marker_names(root, digest)):
            raise _fail("pin_containerfile_stale", "P4", "source.containerfile_sha256")
        status = "stale"
    return PinVerdict(status=status, record_status=record["status"], record_sha256=digest)


def _layout_blob(layout: Path, digest: Any, field: str) -> bytes:
    if not isinstance(digest, str) or _DIGEST.match(digest) is None:
        raise _fail("pin_digest_mismatch", "P9", field)
    try:
        data = _read_regular(layout / "blobs" / "sha256" / _hex(digest))
    except OSError:
        raise _fail("pin_digest_mismatch", "P9", field) from None
    if _sha256(data) != _hex(digest):
        raise _fail("pin_digest_mismatch", "P9", field)
    return data


def assemble_built_record(layout_dir: str | os.PathLike[str],
                          build_meta: Mapping[str, Any]) -> AssembledRecord:
    """Build the ``built`` record from an extracted OCI layout (RRIMAGE §3.4).

    ``build_meta`` holds what the layout cannot: ``oci_archive_sha256``, ``source`` (``commit``,
    ``containerfile_sha256``), ``helper`` (``sha256``, ``source_commit``), ``build`` (every
    schema field except ``tool`` and ``first_manifest_digest``) and ``recorded_at``.
    """
    layout = Path(layout_dir)
    try:
        index = _parse_json(_read_regular(layout / "index.json"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise _fail("pin_digest_mismatch", "P9", "index.json") from None
    descriptors = index.get("manifests") if isinstance(index, Mapping) else None
    if not isinstance(descriptors, list) or len(descriptors) != 1 or not isinstance(descriptors[0], Mapping):
        raise _fail("pin_digest_mismatch", "P9", "index.json.manifests")
    descriptor = descriptors[0]
    media_type = descriptor.get("mediaType")
    if media_type not in MANIFEST_MEDIA_TYPES:
        raise _fail("pin_index_refused", "P3", "index.json.manifests.0.mediaType")
    manifest_bytes = _layout_blob(layout, descriptor.get("digest"), "index.json.manifests.0.digest")
    size = descriptor.get("size")
    if not _strict_integer(None, size) or size != len(manifest_bytes):
        raise _fail("pin_digest_mismatch", "P9", "index.json.manifests.0.size")
    try:
        manifest = _parse_json(manifest_bytes)
    except (UnicodeDecodeError, ValueError):
        raise _fail("pin_digest_mismatch", "P9", "manifest") from None
    if not isinstance(manifest, Mapping):
        raise _fail("pin_digest_mismatch", "P9", "manifest")
    if manifest.get("mediaType") in INDEX_MEDIA_TYPES or "manifests" in manifest:
        raise _fail("pin_index_refused", "P3", "manifest.mediaType")
    config_descriptor = manifest.get("config")
    if not isinstance(config_descriptor, Mapping):
        raise _fail("pin_digest_mismatch", "P9", "manifest.config")
    config_bytes = _layout_blob(layout, config_descriptor.get("digest"), "manifest.config.digest")
    try:
        config = _parse_json(config_bytes)
    except (UnicodeDecodeError, ValueError):
        raise _fail("pin_digest_mismatch", "P9", "config") from None
    if not isinstance(config, Mapping):
        raise _fail("pin_digest_mismatch", "P9", "config")
    if not isinstance(build_meta, Mapping):
        raise _fail("pin_schema_invalid", "P1", "build_meta")
    try:
        manifest_digest = descriptor["digest"]
        build = dict(build_meta["build"])
        if build.pop("first_manifest_digest", manifest_digest) != manifest_digest:
            raise _fail("pin_digest_mismatch", "P9", "build.first_manifest_digest")
        record: dict[str, Any] = {
            "schema": SCHEMA_ID,
            "status": "built",
            "artifact": {
                "oci_archive_sha256": build_meta["oci_archive_sha256"],
                "manifest_digest": manifest_digest,
                "manifest_media_type": media_type,
                "manifest_size": len(manifest_bytes),
                "manifest_path": "plans/evidence/review-runner/manifest.json",
                "config_path": "plans/evidence/review-runner/config.json",
            },
            "platform": {
                "os": config.get("os"),
                "architecture": config.get("architecture"),
                "config_digest": config_descriptor["digest"],
            },
            "source": {
                "repository": "Consiliency/agent-harness",
                "containerfile_path": "phase-loop-runtime/images/review-runner/Containerfile",
                **dict(build_meta["source"]),
            },
            "helper": {
                "path": "/usr/libexec/agent-toolkit/landlock-exec",
                "source_repository": "Consiliency/agent-toolkit",
                **dict(build_meta["helper"]),
            },
            "build": {"tool": "docker buildx", **build, "first_manifest_digest": manifest_digest},
            "image": None,
            "receipt": None,
            "recorded_at": build_meta["recorded_at"],
        }
    except (KeyError, TypeError, ValueError):
        raise _fail("pin_schema_invalid", "P1", "build_meta") from None
    _check_record_only(record)
    _check_p9_bytes(record, manifest_bytes, config_bytes)
    return AssembledRecord(record=record, manifest_bytes=manifest_bytes, config_bytes=config_bytes)


def apply_receipt(record: Mapping[str, Any], receipt: Mapping[str, Any], *,
                  image: Mapping[str, Any], recorded_at: str | None = None) -> dict[str, Any]:
    """Promote a valid ``built`` record to ``pinned`` with ai-stack's receipt.

    ``receipt`` is the schema's ``receipt`` object. ``image`` gives the pushed ``registry``
    and ``repository`` from that receipt; the reference is derived by digest (P2). The result
    passes every record-only rule; P4, P5 and P9 need the checkout, through
    :func:`validate_pin_record`.
    """
    _check_record_only(record)
    if record["status"] != "built":
        raise _fail("pin_schema_invalid", "P1", "status")
    if not isinstance(receipt, Mapping) or not isinstance(image, Mapping):
        raise _fail("pin_schema_invalid", "P1", "receipt")
    pinned = copy.deepcopy(dict(record))
    try:
        registry, repository = image["registry"], image["repository"]
        reference = image.get(
            "reference", f"{registry}/{repository}@{record['artifact']['manifest_digest']}")
    except (KeyError, TypeError):
        raise _fail("pin_schema_invalid", "P1", "image") from None
    pinned["status"] = "pinned"
    pinned["image"] = {"registry": registry, "repository": repository, "reference": reference}
    pinned["receipt"] = copy.deepcopy(dict(receipt))
    pinned["recorded_at"] = recorded_at or datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    _check_record_only(pinned)
    return pinned
