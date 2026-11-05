"""Offline, byte-pinned v1 schema intake. Schema validity confers no authority.

No launch or journal consumer uses this seam until publication reconciliation.
The captured bytes are the only state in a bundle; validators never escape it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from hashlib import sha256
from importlib import metadata, resources
import json
import re
from types import MappingProxyType
from urllib.parse import urldefrag

SOURCE_COMMIT = "93db4b4fcc4e3d40c62f6658b6a67b519c750491"
INPUT_ARTIFACT_SHA256 = "2c98eafb4950cf4106e1512515dca3199cc4c6095dd5c5d6971e7c0e9b62cf0b"
PUBLICATION_PINS = MappingProxyType({
    "admitted-launch-envelope.schema.json": ("0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d", "1abe40abbb1178295af86b3c6d64f9bffe5a0099"),
    "conformance/README.md": ("2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca", "9051f4fcfa7bb91b896f3efe60b6a3b238545a75"),
    "conformance/SHA256SUMS": ("b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285", "ff78301d393ef361f6c476a7117f0d2d97d2193b"),
    "conformance/envelope.vectors.json": ("876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f", "4fcb908f0ed89f2206efc2fbf4c5a6c7bdbd7e56"),
    "conformance/run-status.vectors.json": ("5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730", "4a156e4fbf56526d483f729c78b2e94eb6f48f93"),
    "provenance.json": ("9444d9285e4fbf9fa78c7e10fb474885c79f77cb65abec2f45527af2ec57ff42", "cb2d905ba4fc12c9df1244f301c2624a656643ac"),
    "run-status.schema.json": ("5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30", "8af75b390c1b6dcb5478ac16daec3bd38cb060d1"),
})
_UPSTREAM = tuple(n for n in PUBLICATION_PINS if n != "provenance.json")
_NAMES = (*_UPSTREAM, "harness-provenance.json")
_PROVENANCE_SHA256 = "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a"
_SCHEMAS = MappingProxyType({
    "admitted_launch_envelope.v1": "admitted-launch-envelope.schema.json",
    "supervised_run_status.v1": "run-status.schema.json",
})
_DEFINITIONS = ("journal_line", "projection", "page_request", "page", "reader_view")
_CODES = frozenset(("resource_missing", "digest_mismatch", "manifest_invalid",
    "resource_unlisted", "reference_unlisted", "resource_json_invalid", "schema_invalid",
    "runtime_unsupported", "selector_invalid", "record_json_invalid", "record_schema_invalid"))


class ContractError(ValueError):
    """A closed diagnostic carrying no input values or underlying exception text."""

    def __init__(self, code: str, resource: str | None = None):
        self.code = code if isinstance(code, str) and code in _CODES else "schema_invalid"
        self.resource = resource if isinstance(resource, str) and resource in _NAMES else None
        super().__init__(self.code + (":" + self.resource if self.resource else ""))


@dataclass(frozen=True, slots=True, init=False)
class ContractBundle:
    _captured: tuple[tuple[str, bytes], ...]

    def resource_bytes(self, name: str) -> bytes:
        if not isinstance(name, str) or name not in _NAMES:
            raise ContractError("resource_unlisted") from None
        for key, data in self._captured:
            if key == name:
                return data
        raise ContractError("resource_missing", name) from None


def _strict_json(data: bytes, code: str, resource: str | None = None):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def integer(text):
        value = int(text)
        if not -9007199254740991 <= value <= 9007199254740991:
            raise ValueError()
        return value

    def number(text):
        value = Decimal(text)
        if not value.is_finite() or (value == value.to_integral_value()
                                    and not -9007199254740991 <= value <= 9007199254740991):
            raise ValueError()
        return value

    def constant(_):
        raise ValueError()

    failed = False
    try:
        if type(data) is not bytes:
            raise ValueError()
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_int=integer, parse_float=number, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError, RecursionError, InvalidOperation):
        failed = True
    if failed:
        raise ContractError(code, resource) from None
    return value


def _runtime():
    failed = False
    try:
        from jsonschema import Draft202012Validator, ValidationError, validators
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
        version = tuple(int(x) for x in metadata.version("jsonschema").split(".")[:2])
        if version < (4, 18):
            raise ValueError()
        # Probe the supported constructor/API, never a legacy resolver.
        registry = Registry(retrieve=_deny_reference)
        registry = registry.with_resource("urn:probe", Resource({}, DRAFT202012))
        Draft202012Validator({}, registry=registry)
    except (ImportError, AttributeError, TypeError, ValueError, metadata.PackageNotFoundError):
        failed = True
    if failed:
        raise ContractError("runtime_unsupported") from None

    def pattern(validator, expression, instance, schema):
        if isinstance(instance, str):
            # The pinned vocabulary uses only this pattern. Python's $ also
            # accepts a final LF; ECMA-262 without multiline requires the end.
            if expression == "^[0-9a-f]{64}$":
                expression = r"^[0-9a-f]{64}\Z"
            if re.search(expression, instance) is None:
                yield ValidationError("record_schema_invalid")

    integers = Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda checker, value:
        (type(value) is int or (isinstance(value, (float, Decimal)) and value == int(value))))
    compatible = validators.extend(Draft202012Validator, {"pattern": pattern}, type_checker=integers)
    return compatible, Registry, Resource, DRAFT202012


def _deny_reference(_):
    raise ContractError("reference_unlisted") from None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _schema_runtime(captured):
    return _cached_schema_runtime(tuple(captured.items()))


@lru_cache(maxsize=4)
def _cached_schema_runtime(buffers):
    captured = dict(buffers)
    validator, Registry, Resource, specification = _runtime()
    schemas = {n: _strict_json(captured[n], "resource_json_invalid", n) for n in _SCHEMAS.values()}
    if any(not isinstance(schema, dict) for schema in schemas.values()):
        raise ContractError("schema_invalid") from None
    ids = {s.get("$id"): s for s in schemas.values()}
    if set(ids) != {"urn:contract:" + family for family in _SCHEMAS}:
        raise ContractError("schema_invalid") from None
    for name, schema in schemas.items():
        for node in _walk(schema):
            if "$ref" not in node:
                continue
            ref = node["$ref"]
            base, fragment = urldefrag(ref) if isinstance(ref, str) else ("!", "")
            target = schema if not base else ids.get(base)
            if target is None or (fragment and not fragment.startswith("/")):
                raise ContractError("reference_unlisted", name) from None
            missing = False
            try:
                for token in fragment.split("/")[1:]:
                    target = target[token.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError, IndexError):
                missing = True
            if missing:
                raise ContractError("reference_unlisted", name) from None
        failed = False
        try:
            validator.check_schema(schema)
        except Exception:
            failed = True
        if failed:
            raise ContractError("schema_invalid", name) from None
    registry = Registry(retrieve=_deny_reference).with_resources(
        (s["$id"], Resource(s, specification)) for s in schemas.values())
    return validator, registry, schemas


def load_contract_bundle() -> ContractBundle:
    captured = {}
    root = resources.files("phase_loop_runtime").joinpath("schemas", "supervised-worker-v1")
    for name in _NAMES:
        failed = False
        try:
            data = root.joinpath(name).read_bytes()
        except (OSError, ValueError):
            failed = True
        if failed:
            raise ContractError("resource_missing", name) from None
        expected = _PROVENANCE_SHA256 if name == "harness-provenance.json" else PUBLICATION_PINS[name][0]
        if sha256(data).hexdigest() != expected:
            raise ContractError("digest_mismatch", name) from None
        captured[name] = data
    parsed = {n: _strict_json(b, "resource_json_invalid", n)
              for n, b in captured.items() if n.endswith(".json")}
    provenance = parsed["harness-provenance.json"]
    expected_resources = {n: {"sha256": PUBLICATION_PINS[n][0], "blob": PUBLICATION_PINS[n][1]}
                          for n in _UPSTREAM}
    if (not isinstance(provenance, dict) or provenance.get("commit") != SOURCE_COMMIT
            or provenance.get("source_repository") != "https://github.com/Consiliency/consiliency-contract"
            or provenance.get("root") != "core/supervised-run/"
            or provenance.get("upstream_resources") != expected_resources
            or provenance.get("excluded_metadata") != {"provenance.json": {
                "sha256": PUBLICATION_PINS["provenance.json"][0], "blob": PUBLICATION_PINS["provenance.json"][1]}}
            or provenance.get("input_artifact_sha256") != INPUT_ARTIFACT_SHA256
            or provenance.get("byte_pin_authority") is not False):
        raise ContractError("manifest_invalid", "harness-provenance.json") from None
    manifest = captured["conformance/SHA256SUMS"].decode("ascii")
    expected_manifest = {("../" + n if not n.startswith("conformance/") else n.removeprefix("conformance/")): PUBLICATION_PINS[n][0]
                         for n in _UPSTREAM if n != "conformance/SHA256SUMS"}
    entries = {}
    invalid = False
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None or match[2] in entries:
            invalid = True
        else:
            entries[match[2]] = match[1]
    if invalid or entries != expected_manifest:
        raise ContractError("manifest_invalid", "conformance/SHA256SUMS") from None
    _schema_runtime(captured)
    bundle = object.__new__(ContractBundle)
    object.__setattr__(bundle, "_captured", tuple(captured.items()))
    return bundle


def validate_record(bundle: ContractBundle, family: str, record: bytes, *, definition=None) -> None:
    if not isinstance(family, str) or family not in _SCHEMAS:
        raise ContractError("selector_invalid") from None
    if (family == "admitted_launch_envelope.v1" and definition is not None) or (
            family == "supervised_run_status.v1" and definition is not None
            and (not isinstance(definition, str) or definition not in _DEFINITIONS)):
        raise ContractError("selector_invalid") from None
    instance = _strict_json(record, "record_json_invalid")
    validator, registry, schemas = _schema_runtime(dict(bundle._captured))
    name = _SCHEMAS[family]
    schema = schemas[name]
    if family == "supervised_run_status.v1":
        schema = {"$ref": schema["$id"] + "#/$defs/" + (definition or "journal_line")}
    failed = False
    try:
        failed = next(validator(schema, registry=registry).iter_errors(instance), None) is not None
    except Exception:
        failed = True
    if failed:
        raise ContractError("record_schema_invalid", name) from None
