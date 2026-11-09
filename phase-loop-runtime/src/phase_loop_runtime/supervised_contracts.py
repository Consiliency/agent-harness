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
V2_SOURCE_COMMIT = "2b91ef85bfdc76239ae52806b3318513951543ab"
V2_INPUT_ARTIFACT_SHA256 = "b6fd84dc91b91236e72f4359ef7f0673c3a851ed2366d7ffdfc99ad10466e330"
V2_PUBLICATION_PINS = MappingProxyType({'admitted-launch-envelope.schema.json': ('0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d', '1abe40abbb1178295af86b3c6d64f9bffe5a0099'), 'admitted-launch-envelope.v2.schema.json': ('6d6b2f89c55d160c2c132c29b3aa330a0a91c40ab017707040478a60b469194f', '79d3d0f4bd3af1417e06e0f2255fa3f4e7749770'), 'conformance/README.md': ('2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca', '9051f4fcfa7bb91b896f3efe60b6a3b238545a75'), 'conformance/README.v2.md': ('c6ab5d9da4707adf5dad9602b483b201a2dfe89f638ecba84129e0c477d72637', '3409e2b7f9a8582af3796a82e1c15b7cb2c17fdb'), 'conformance/SHA256SUMS': ('48904c259e4a1c24d3e841f56b6c2a84ce2cff32014cf573b3e41b34fac1f1fc', '9bbcd0b8bc6449377b94debfe0568bfe6d685e07'), 'conformance/envelope.v2.apply.vectors.json': ('57e0fd4d2e88c75bb8dfbab94448431ca3c752f6444febf1bd492323b044c078', '24a46480c3d7384e929233e9713d923bc6e0809f'), 'conformance/envelope.v2.canonical.vectors.json': ('f7f11c7667d12b0c876102781fdd5773074f5301f152a6d18be509894bc0e8f8', '8111d2e6f75f6bdb68c48d2963f3c4649596cbe8'), 'conformance/envelope.v2.vectors.json': ('e742d2774d410c2508405eaffed84575b992483da68c07f28591097d6ec5bc2f', '2028d84f0b5be0d0c4dd6e8ec06ab377d2dd3c0b'), 'conformance/envelope.vectors.json': ('876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f', '4fcb908f0ed89f2206efc2fbf4c5a6c7bdbd7e56'), 'conformance/run-status.vectors.json': ('5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730', '4a156e4fbf56526d483f729c78b2e94eb6f48f93'), 'provenance.json': ('f4b306fd7608c123d751225d02591e94654255fc688b5f84b777d2e896cf46f7', '46bbff61b179b294ce2c481ccfc58a62c666e9b5'), 'run-status.schema.json': ('5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30', '8af75b390c1b6dcb5478ac16daec3bd38cb060d1'), 'version/core/schemas/version-skew-protocol.schema.json': ('d77624c1975e896309c88a57b6e3690b3b24ab438873d0fb6873dd4924dd1c8f', 'b6f23cd9107b85f8db20804e0f9cc0d48613f930'), 'version/pyproject.toml.pinned': ('0aee475b360d5c17673000c53fefd742ed88e4d6d4194bf9d77155e568ab5153', 'b0ae3eae3ed89c9629a203efe71bdfb895042e36'), 'version/package.json.pinned': ('bd85b4e580d430983368749852a0e6e82e783e4464e7a0ed24996c4306e1e81c', '04fc4ecc713ad2841c88a38e0409ff50ea602b51')})
_V2_NAMES = (*tuple(n for n in V2_PUBLICATION_PINS if n != "provenance.json"), "harness-provenance.json")
_V2_PROVENANCE_SHA256 = '771bcb9c6dd2cb1421f007a74f96c6ee8fd2309731cd75b6c35516c5e93f4cda'
_V2_SCHEMAS = MappingProxyType({**_SCHEMAS, "admitted_launch_envelope.v2": "admitted-launch-envelope.v2.schema.json"})

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
        if not isinstance(name, str) or name not in dict(self._captured):
            raise ContractError("resource_unlisted") from None
        for key, data in self._captured:
            if key == name:
                return data
        raise ContractError("resource_missing", name) from None


def _strict_json(data: bytes, code: str, resource: str | None = None):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result or any(0xD800 <= ord(c) <= 0xDFFF for c in key):
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
        def strings(item):
            if isinstance(item, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise ValueError()
            if isinstance(item, dict):
                for child in item.values():
                    strings(child)
            elif isinstance(item, list):
                for child in item:
                    strings(child)
        strings(value)
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
            if expression.endswith("$"):
                expression = expression[:-1] + r"\Z"
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
    families = _V2_SCHEMAS if "admitted-launch-envelope.v2.schema.json" in captured else _SCHEMAS
    schemas = {n: _strict_json(captured[n], "resource_json_invalid", n) for n in families.values()}
    if any(not isinstance(schema, dict) for schema in schemas.values()):
        raise ContractError("schema_invalid") from None
    ids = {s.get("$id"): s for s in schemas.values()}
    if set(ids) != {"urn:contract:" + family for family in families}:
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


def load_contract_bundle(*, version: str = "v1") -> ContractBundle:
    if type(version) is not str or version not in ("v1", "v2"):
        raise ContractError("selector_invalid") from None
    if version == "v2":
        return _load_v2_bundle()
    captured = {}
    root = resources.files("phase_loop_runtime").joinpath("schemas", "supervised-worker-v1")
    observed = set()
    def inventory(directory, prefix=""):
        for child in directory.iterdir():
            name = prefix + child.name
            if child.is_dir() and any(n.startswith(name + "/") for n in _NAMES):
                inventory(child, name + "/")
            elif child.is_file() and name in _NAMES:
                observed.add(name)
            else:
                raise ContractError("resource_unlisted") from None
    failed = False
    try:
        inventory(root)
    except (OSError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        failed = True
    if failed:
        raise ContractError("resource_missing") from None
    for name in _NAMES:
        if name not in observed:
            raise ContractError("resource_missing", name) from None
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
    invalid = False
    try:
        manifest = captured["conformance/SHA256SUMS"].decode("ascii")
    except UnicodeError:
        invalid = True
    if invalid:
        raise ContractError("manifest_invalid", "conformance/SHA256SUMS") from None
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
    captured = getattr(bundle, "_captured", None) if type(bundle) is ContractBundle else None
    v2 = type(captured) is tuple and any(row[0] == "admitted-launch-envelope.v2.schema.json" for row in captured if type(row) is tuple and len(row) == 2)
    names = _V2_NAMES if v2 else _NAMES
    pins = V2_PUBLICATION_PINS if v2 else PUBLICATION_PINS
    provenance_digest = _V2_PROVENANCE_SHA256 if v2 else _PROVENANCE_SHA256
    families = _V2_SCHEMAS if v2 else _SCHEMAS
    if not isinstance(family, str) or family not in families:
        raise ContractError("selector_invalid") from None
    if (family.startswith("admitted_launch_envelope.") and definition is not None) or (
            family == "supervised_run_status.v1" and definition is not None
            and (not isinstance(definition, str) or definition not in _DEFINITIONS)):
        raise ContractError("selector_invalid") from None
    captured = getattr(bundle, "_captured", None) if type(bundle) is ContractBundle else None
    if (type(captured) is not tuple or len(captured) != len(names)
            or any(type(row) is not tuple or len(row) != 2 or row[0] != name
                   or type(row[1]) is not bytes
                   or sha256(row[1]).hexdigest() != (provenance_digest if name == "harness-provenance.json" else pins[name][0])
                   for name, row in zip(names, captured))):
        raise ContractError("manifest_invalid") from None
    instance = _v2_json(record) if v2 and family == "admitted_launch_envelope.v2" else _strict_json(record, "record_json_invalid")
    validator, registry, schemas = _schema_runtime(dict(bundle._captured))
    name = families[family]
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


def _v2_json(raw: bytes):
    """Validate both original numeric tokens and their binary64 representation."""
    import math

    def number(token):
        value = Decimal(token)
        rounded = float(value)
        if (not math.isfinite(rounded)
                or (value == value.to_integral_value() and abs(value) > 9007199254740991)
                or (rounded.is_integer() and abs(rounded) > 9007199254740991)):
            raise ValueError()
        return rounded

    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def constant(_):
        raise ValueError()

    def strings(value):
        if isinstance(value, str):
            value.encode("utf-8")
        elif isinstance(value, dict):
            for key, child in value.items():
                strings(key)
                strings(child)
        elif isinstance(value, list):
            for child in value:
                strings(child)

    failed = False
    try:
        if type(raw) is not bytes:
            raise ValueError()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_int=number, parse_float=number, parse_constant=constant)
        strings(value)
    except (ValueError, TypeError, UnicodeError, OverflowError, InvalidOperation, RecursionError):
        failed = True
    if failed:
        raise ContractError("record_json_invalid") from None
    return value


def _load_v2_bundle():
    import tomllib

    root = resources.files("phase_loop_runtime").joinpath("schemas", "supervised-worker-v2")
    captured = {}
    observed = set()

    def inventory(directory, prefix=""):
        for child in directory.iterdir():
            name = prefix + child.name
            if child.is_dir() and any(n.startswith(name + "/") for n in _V2_NAMES):
                inventory(child, name + "/")
            elif child.is_file() and name in _V2_NAMES:
                observed.add(name)
            else:
                raise ContractError("resource_unlisted") from None

    failed = False
    try:
        inventory(root)
        for name in _V2_NAMES:
            if name not in observed:
                raise ContractError("resource_missing") from None
            data = root.joinpath(name).read_bytes()
            expected = _V2_PROVENANCE_SHA256 if name == "harness-provenance.json" else V2_PUBLICATION_PINS[name][0]
            if sha256(data).hexdigest() != expected:
                raise ContractError("digest_mismatch") from None
            captured[name] = data
    except OSError:
        failed = True
    if failed:
        raise ContractError("resource_missing") from None
    provenance = _strict_json(captured["harness-provenance.json"], "resource_json_invalid")
    expected_resources = {n: {"sha256": d, "blob": b} for n, (d, b) in V2_PUBLICATION_PINS.items()
                          if n != "provenance.json"}
    if (provenance.get("byte_pin_authority") is not False
            or provenance.get("publisher_status") != "provisional"
            or provenance.get("commit") != V2_SOURCE_COMMIT
            or provenance.get("input_artifact_sha256") != V2_INPUT_ARTIFACT_SHA256
            or provenance.get("upstream_resources") != expected_resources
            or provenance.get("excluded_metadata") != {"provenance.json": dict(zip(("sha256", "blob"), V2_PUBLICATION_PINS["provenance.json"]))}
            or provenance.get("source_repository") != "https://github.com/Consiliency/consiliency-contract"
            or provenance.get("root") != "core/supervised-run/"):
        raise ContractError("manifest_invalid") from None
    failed = False
    try:
        declarations = (
            tomllib.loads(captured["version/pyproject.toml.pinned"].decode())["project"]["version"],
            _strict_json(captured["version/package.json.pinned"], "manifest_invalid")["version"],
        )
        skew = _strict_json(captured["version/core/schemas/version-skew-protocol.schema.json"], "manifest_invalid")
        properties = skew["properties"]
        ranges = properties["compatible_ranges"]["properties"]
        if (declarations != ("0.7.0", "0.7.0")
                or properties["contract_version"]["const"] != "0.7.0"
                or any(ranges[name]["const"] != ">=0.7.0 <0.8.0" for name in ("contract", "package"))):
            raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError):
        failed = True
    if failed:
        raise ContractError("manifest_invalid") from None
    manifest = captured["conformance/SHA256SUMS"].decode("ascii")
    expected = {("../" + n if not n.startswith("conformance/") else n.removeprefix("conformance/")): d
                for n, (d, _) in V2_PUBLICATION_PINS.items()
                if not n.startswith("version/") and n not in ("provenance.json", "conformance/SHA256SUMS")}
    entries = {}
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None or match[2] in entries:
            raise ContractError("manifest_invalid") from None
        entries[match[2]] = match[1]
    if entries != expected:
        raise ContractError("manifest_invalid") from None
    _schema_runtime(captured)
    bundle = object.__new__(ContractBundle)
    object.__setattr__(bundle, "_captured", tuple(captured.items()))
    return bundle


@dataclass(frozen=True)
class _CorpusNumber:
    token: str


def _corpus_value(raw: bytes):
    """Private corpus containers retain deliberately invalid record tokens."""
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def constant(_):
        raise ValueError()

    failed = False
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_int=_CorpusNumber, parse_float=_CorpusNumber, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        failed = True
    if failed:
        raise ContractError("resource_json_invalid") from None
    return value


def _corpus_bytes(value):
    """Reconstruct raw case bytes without normalizing number or string domains."""
    if type(value) is _CorpusNumber:
        return value.token.encode("ascii")
    if isinstance(value, dict):
        return b"{" + b",".join(json.dumps(k, ensure_ascii=True).encode("ascii") + b":" + _corpus_bytes(v)
                                 for k, v in value.items()) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(_corpus_bytes(v) for v in value) + b"]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
