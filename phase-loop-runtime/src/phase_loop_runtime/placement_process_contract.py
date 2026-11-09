"""The placement process protocol v1: packaged schema, strict codec and typed records.

The schema is the frozen planning artifact ``plans/artifacts/v13-PLACECLI-contract-v1.schema.json``
(erratum PLACECLI-v1-errata-1), shipped byte for byte as package data at
``contracts/placement/process-v1.schema.json`` and read through :mod:`importlib.resources`.
Its SHA-256 is the wire identity a client checks with ``version``.

Decoding is side-effect free. Input bytes are captured once, checked against the input rules
of ``x-cli.input`` (UTF-8, one JSON object, no duplicate keys, no non-finite or unsafe
numbers, no trailing data, at most 65536 bytes), validated against the message definition
for the verb, and only then turned into immutable records. Every failure is a
:class:`ProtocolError` whose ``code`` is one closed diagnostic; no input value, exception
chain or path reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from importlib import resources
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Union

import jsonschema
import rfc8785

__all__ = [
    "BRIDGE_DIRECTORY_MODE",
    "BRIDGE_SOCKET_MODE",
    "CLIENTS",
    "CLIENT_WORKLOADS",
    "MAX_INPUT_BYTES",
    "PROTOCOL_DIAGNOSTICS",
    "VERBS",
    "BridgeDescriptor",
    "InventoryReapResult",
    "LeaseFlags",
    "LocalHeadroomConfig",
    "PlacementRequestMessage",
    "PlacementResponseMessage",
    "PlacementTarget",
    "ProtocolError",
    "ReapRequest",
    "ReapResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "Reservation",
    "ReserveRequest",
    "ReserveResponse",
    "TrailEntry",
    "VersionResponse",
    "canonical_bytes",
    "decode_request",
    "decode_response",
    "encode_response",
    "exit_class",
    "load_strict_object",
    "protocol_schema_sha256",
    "require_empty_version_input",
    "schema_bytes",
    "validate_message",
]

SCHEMA_RESOURCE = "contracts/placement/process-v1.schema.json"
MAX_INPUT_BYTES = 65536
VERBS: tuple[str, ...] = ("reserve", "release", "reap", "version")
CLIENTS: tuple[str, ...] = ("agent-harness", "agent-toolkit")
#: ``x-identity-inventories``: the workloads each client may reserve.
CLIENT_WORKLOADS: Mapping[str, frozenset[str]] = MappingProxyType({
    "agent-harness": frozenset({"leg", "qualification", "implementation"}),
    "agent-toolkit": frozenset({"pi-runner"}),
})
BRIDGE_DIRECTORY_MODE = 0o700
BRIDGE_SOCKET_MODE = 0o600

#: The closed diagnostics a :class:`ProtocolError` carries.
PROTOCOL_DIAGNOSTICS: frozenset[str] = frozenset({
    "input_not_bytes",
    "input_too_large",
    "input_not_utf8",
    "input_invalid_json",
    "input_duplicate_key",
    "input_non_finite_number",
    "input_unsafe_number",
    "input_trailing_data",
    "input_not_object",
    "version_input_not_empty",
    "verb_unknown",
    "schema_invalid",
    "response_invalid",
    "schema_unavailable",
})

_REQUEST_DEFS = MappingProxyType({
    "reserve": "ReserveRequest", "release": "ReleaseRequest", "reap": "ReapRequest",
})
_RESPONSE_DEFS = MappingProxyType({
    "reserve": "ReserveResponse", "release": "ReleaseResponse", "reap": "ReapResponse",
    "version": "VersionResponse",
})
_SAFE_INTEGER = 2 ** 53 - 1
_JSON_WHITESPACE = " \t\n\r"
_DATE_TIME = re.compile(
    r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])[Tt]([01][0-9]|2[0-3]):[0-5][0-9]:"
    r"([0-5][0-9]|60)(\.[0-9]+)?([Zz]|[+-]([01][0-9]|2[0-3]):[0-5][0-9])"
)


class ProtocolError(ValueError):
    """A protocol failure (exit class 70). ``str()`` is the closed diagnostic only."""

    def __init__(self, code: str) -> None:
        if code not in PROTOCOL_DIAGNOSTICS:
            code = "schema_invalid"
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return self.code


# -- the packaged schema ------------------------------------------------------------------

@lru_cache(maxsize=1)
def schema_bytes() -> bytes:
    """The packaged protocol schema, exactly as shipped."""
    try:
        return resources.files(__package__).joinpath(SCHEMA_RESOURCE).read_bytes()
    except (OSError, ValueError):
        raise ProtocolError("schema_unavailable") from None


def protocol_schema_sha256() -> str:
    """``VersionResponse.protocol_schema_sha256``: lowercase hex of the packaged bytes."""
    return hashlib.sha256(schema_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _schema_document() -> Mapping[str, Any]:
    try:
        return json.loads(schema_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError("schema_unavailable") from None


def _strict_integer(_checker: object, instance: object) -> bool:
    return isinstance(instance, int) and not isinstance(instance, bool)


def _date_time(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    return _DATE_TIME.fullmatch(instance) is not None


_FORMATS = jsonschema.FormatChecker(formats=())
_FORMATS.checks("date-time")(_date_time)
_Validator = jsonschema.validators.extend(
    jsonschema.Draft202012Validator,
    type_checker=jsonschema.Draft202012Validator.TYPE_CHECKER.redefine("integer", _strict_integer),
)


@lru_cache(maxsize=None)
def _validator(definition: str) -> Any:
    document = dict(_schema_document())
    document.pop("oneOf", None)
    document["$ref"] = f"#/$defs/{definition}"
    return _Validator(document, format_checker=_FORMATS)


def _valid(definition: str, instance: object) -> bool:
    try:
        return _validator(definition).is_valid(instance)
    except (jsonschema.exceptions.SchemaError, RecursionError, TypeError, ValueError):
        return False


# -- strict input capture -----------------------------------------------------------------

def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("input_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_name: str) -> Any:
    raise ProtocolError("input_non_finite_number")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ProtocolError("input_non_finite_number")
    return value


def _safe_int(text: str) -> int:
    if len(text.lstrip("-")) > 16:
        raise ProtocolError("input_unsafe_number")
    value = int(text)
    if abs(value) > _SAFE_INTEGER:
        raise ProtocolError("input_unsafe_number")
    return value


def _encodable(value: object) -> bool:
    """No lone surrogate (``"\\ud800"``) survives into a record or an echo."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(value, dict):
        return all(_encodable(k) and _encodable(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_encodable(v) for v in value)
    return True


def _load_object(raw: bytes) -> dict[str, Any]:
    """Capture once and parse under the input rules; raise a closed :class:`ProtocolError`."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ProtocolError("input_not_bytes")
    captured = bytes(raw)
    if len(captured) > MAX_INPUT_BYTES:
        raise ProtocolError("input_too_large")
    try:
        text = captured.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ProtocolError("input_not_utf8") from None
    if text.startswith("﻿"):
        raise ProtocolError("input_not_utf8")
    decoder = json.JSONDecoder(
        object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        parse_float=_finite_float, parse_int=_safe_int,
    )
    start = len(text) - len(text.lstrip(_JSON_WHITESPACE))
    try:
        value, end = decoder.raw_decode(text, start)
    except ProtocolError:
        raise
    except (ValueError, RecursionError):
        raise ProtocolError("input_invalid_json") from None
    if text[end:].strip(_JSON_WHITESPACE):
        raise ProtocolError("input_trailing_data")
    if not isinstance(value, dict):
        raise ProtocolError("input_not_object")
    if not _encodable(value):
        raise ProtocolError("input_not_utf8")
    return value


def load_strict_object(raw: bytes) -> dict[str, Any]:
    """Parse one JSON object under the protocol's input rules (no schema)."""
    return _load_object(raw)


def require_empty_version_input(raw: bytes) -> None:
    """``version`` requires empty stdin."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ProtocolError("input_not_bytes")
    if len(bytes(raw)) != 0:
        raise ProtocolError("version_input_not_empty")


def canonical_bytes(value: object) -> bytes:
    """The UTF-8 RFC 8785 serialization the protocol's digests are taken over."""
    return rfc8785.dumps(value)


# -- immutable records --------------------------------------------------------------------

def _context(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class PlacementTarget:
    name: str
    kind: str
    rank: int

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "rank": self.rank}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "PlacementTarget":
        return cls(value["name"], value["kind"], value["rank"])


@dataclass(frozen=True)
class TrailEntry:
    target: str
    outcome: str
    code: str | None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"target": self.target, "outcome": self.outcome, "code": self.code,
                "reason": self.reason}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "TrailEntry":
        return cls(value["target"], value["outcome"], value["code"], value["reason"])


_FLAG_NAMES = ("reserved", "create_settled", "ready", "exec_claimed", "fenced",
               "destruction_observed", "cleanup_pending", "barrier_confirmed", "expired")


@dataclass(frozen=True)
class LeaseFlags:
    reserved: bool = False
    create_settled: bool = False
    ready: bool = False
    exec_claimed: bool = False
    fenced: bool = False
    destruction_observed: bool = False
    cleanup_pending: bool = False
    barrier_confirmed: bool = False
    expired: bool = False

    def to_json(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in _FLAG_NAMES}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LeaseFlags":
        return cls(**{name: bool(value[name]) for name in _FLAG_NAMES})


@dataclass(frozen=True)
class BridgeDescriptor:
    """``$defs.ForwardTcpUnixBridge``: where the reservation's bridge socket is."""

    service_name: str
    socket_path: str

    def to_json(self) -> dict[str, Any]:
        return {"kind": "forward_tcp_unix", "service_name": self.service_name,
                "socket_path": self.socket_path, "directory_mode": "0700",
                "socket_mode": "0600", "lifetime": "reservation"}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "BridgeDescriptor":
        return cls(value["service_name"], value["socket_path"])


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    workload: str
    target: PlacementTarget
    transport_id: str
    image_digest: str
    policy_vector: str
    policy_digest: str
    providers: tuple[str, ...]
    egress_sha256: str
    client: str
    inventory: str
    rank_policy: str
    lease_id: str | None
    expires_at: str | None
    config_sha256: str
    bridge: BridgeDescriptor | None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": "placement.reservation.v1",
            "reservation_id": self.reservation_id,
            "workload": self.workload,
            "target": self.target.to_json(),
            "transport_id": self.transport_id,
            "image_digest": self.image_digest,
            "policy_vector": self.policy_vector,
            "policy_digest": self.policy_digest,
            "providers": list(self.providers),
            "egress_sha256": self.egress_sha256,
            "client": self.client,
            "inventory": self.inventory,
            "rank_policy": self.rank_policy,
            "lease_id": self.lease_id,
            "expires_at": self.expires_at,
            "config_sha256": self.config_sha256,
            "bridge": None if self.bridge is None else self.bridge.to_json(),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Reservation":
        bridge = value["bridge"]
        return cls(
            value["reservation_id"], value["workload"], PlacementTarget.from_json(value["target"]),
            value["transport_id"], value["image_digest"], value["policy_vector"],
            value["policy_digest"], tuple(value["providers"]), value["egress_sha256"],
            value["client"], value["inventory"], value["rank_policy"], value["lease_id"],
            value["expires_at"], value["config_sha256"],
            None if bridge is None else BridgeDescriptor.from_json(bridge),
        )


@dataclass(frozen=True)
class ReserveRequest:
    request_id: str
    workload: str
    ttl_s: int
    image_digest: str
    policy_vector: str
    providers: tuple[str, ...]
    deadline_ms: int
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.reserve.request.v1", "request_id": self.request_id,
                "workload": self.workload, "ttl_s": self.ttl_s,
                "image_digest": self.image_digest, "policy_vector": self.policy_vector,
                "providers": list(self.providers), "deadline_ms": self.deadline_ms,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReserveRequest":
        return cls(value["request_id"], value["workload"], value["ttl_s"],
                   value["image_digest"], value["policy_vector"], tuple(value["providers"]),
                   value["deadline_ms"], _context(value["caller_context"]))


@dataclass(frozen=True)
class ReleaseRequest:
    request_id: str
    reservation: Reservation
    deadline_ms: int
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))
    #: The reservation member exactly as the caller sent it, for the echo comparison.
    reservation_json: Mapping[str, Any] = field(default_factory=lambda: _context({}),
                                                repr=False, compare=False)

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.release.request.v1", "request_id": self.request_id,
                "reservation": self.reservation.to_json(), "deadline_ms": self.deadline_ms,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReleaseRequest":
        return cls(value["request_id"], Reservation.from_json(value["reservation"]),
                   value["deadline_ms"], _context(value["caller_context"]),
                   _context(value["reservation"]))


@dataclass(frozen=True)
class ReapRequest:
    request_id: str
    deadline_ms: int
    max_items: int
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.reap.request.v1", "request_id": self.request_id,
                "scope": "caller_inventory", "deadline_ms": self.deadline_ms,
                "max_items": self.max_items, "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReapRequest":
        return cls(value["request_id"], value["deadline_ms"], value["max_items"],
                   _context(value["caller_context"]))


@dataclass(frozen=True)
class ReserveResponse:
    request_id: str
    outcome: str
    code: str | None
    reason: str | None
    reservation: Reservation | None
    trail: tuple[TrailEntry, ...]
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.reserve.response.v1", "request_id": self.request_id,
                "outcome": self.outcome, "code": self.code, "reason": self.reason,
                "reservation": None if self.reservation is None else self.reservation.to_json(),
                "trail": [entry.to_json() for entry in self.trail],
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReserveResponse":
        reservation = value["reservation"]
        return cls(value["request_id"], value["outcome"], value["code"], value["reason"],
                   None if reservation is None else Reservation.from_json(reservation),
                   tuple(TrailEntry.from_json(entry) for entry in value["trail"]),
                   _context(value["caller_context"]))


@dataclass(frozen=True)
class ReleaseResponse:
    request_id: str
    reservation_id: str
    state: str
    code: str | None
    flags: LeaseFlags
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.release.response.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id, "state": self.state, "code": self.code,
                "flags": self.flags.to_json(), "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReleaseResponse":
        return cls(value["request_id"], value["reservation_id"], value["state"], value["code"],
                   LeaseFlags.from_json(value["flags"]), _context(value["caller_context"]))


@dataclass(frozen=True)
class InventoryReapResult:
    client: str
    inventory: str
    examined: int
    destroyed: int
    pending: int
    code: str | None

    def to_json(self) -> dict[str, Any]:
        return {"client": self.client, "inventory": self.inventory, "examined": self.examined,
                "destroyed": self.destroyed, "pending": self.pending, "code": self.code}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "InventoryReapResult":
        return cls(value["client"], value["inventory"], value["examined"], value["destroyed"],
                   value["pending"], value["code"])


@dataclass(frozen=True)
class ReapResponse:
    request_id: str
    state: str
    inventory: InventoryReapResult
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.reap.response.v1", "request_id": self.request_id,
                "state": self.state, "inventories": [self.inventory.to_json()],
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReapResponse":
        return cls(value["request_id"], value["state"],
                   InventoryReapResult.from_json(value["inventories"][0]),
                   _context(value["caller_context"]))


_HEADROOM_NAMES = (
    "memory_available_bytes_minimum_floor",
    "memory_available_total_ram_fraction_minimum",
    "load_per_cpu_percent_maximum_exclusive",
    "io_pressure_full_avg10_percent_maximum_exclusive",
    "memory_pressure_some_avg10_percent_maximum_exclusive",
    "live_sandboxes_maximum_exclusive",
    "observation_age_seconds_maximum",
)


@dataclass(frozen=True)
class LocalHeadroomConfig:
    """``$defs.LocalHeadroomConfig``: the effective local-admission thresholds."""

    memory_available_bytes_minimum_floor: int
    memory_available_total_ram_fraction_minimum: float
    load_per_cpu_percent_maximum_exclusive: float
    io_pressure_full_avg10_percent_maximum_exclusive: float
    memory_pressure_some_avg10_percent_maximum_exclusive: float
    live_sandboxes_maximum_exclusive: int
    observation_age_seconds_maximum: float

    def __post_init__(self) -> None:
        if not _valid("LocalHeadroomConfig", self.to_json()):
            raise ProtocolError("schema_invalid")

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _HEADROOM_NAMES}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LocalHeadroomConfig":
        if not isinstance(value, Mapping) or set(value) != set(_HEADROOM_NAMES):
            raise ProtocolError("schema_invalid")
        return cls(**{name: value[name] for name in _HEADROOM_NAMES})


@dataclass(frozen=True)
class VersionResponse:
    client: str
    protocol_schema_sha256: str
    config_sha256: str
    local_headroom: LocalHeadroomConfig

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.version.response.v1", "client": self.client,
                "protocol_schema_sha256": self.protocol_schema_sha256,
                "config_sha256": self.config_sha256,
                "local_headroom": self.local_headroom.to_json()}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "VersionResponse":
        return cls(value["client"], value["protocol_schema_sha256"], value["config_sha256"],
                   LocalHeadroomConfig.from_json(value["local_headroom"]))


PlacementRequestMessage = Union[ReserveRequest, ReleaseRequest, ReapRequest]
PlacementResponseMessage = Union[ReserveResponse, ReleaseResponse, ReapResponse, VersionResponse]

_REQUEST_TYPES: Mapping[str, Any] = MappingProxyType({
    "reserve": ReserveRequest, "release": ReleaseRequest, "reap": ReapRequest,
})
_RESPONSE_TYPES: Mapping[type, str] = MappingProxyType({
    ReserveResponse: "ReserveResponse", ReleaseResponse: "ReleaseResponse",
    ReapResponse: "ReapResponse", VersionResponse: "VersionResponse",
})
_RESPONSE_RECORDS: Mapping[str, Any] = MappingProxyType({
    "reserve": ReserveResponse, "release": ReleaseResponse, "reap": ReapResponse,
    "version": VersionResponse,
})


# -- the codec ----------------------------------------------------------------------------

def decode_request(verb: str, raw: bytes) -> PlacementRequestMessage:
    """Decode one request for ``reserve``, ``release`` or ``reap``.

    The bytes are captured once; the record is built only from that capture after it
    passed the input rules and the verb's schema. Raises :class:`ProtocolError`."""
    definition = _REQUEST_DEFS.get(verb) if isinstance(verb, str) else None
    if definition is None:
        raise ProtocolError("verb_unknown")
    value = _load_object(raw)
    if not _valid(definition, value):
        raise ProtocolError("schema_invalid")
    try:
        return _REQUEST_TYPES[verb].from_json(value)
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("schema_invalid") from None


def encode_response(message: PlacementResponseMessage) -> bytes:
    """One compact UTF-8 JSON object followed by LF, validated before it is returned."""
    definition = _RESPONSE_TYPES.get(type(message))
    if definition is None:
        raise ProtocolError("response_invalid")
    try:
        value = message.to_json()
    except (AttributeError, TypeError, ValueError):
        raise ProtocolError("response_invalid") from None
    if not _valid(definition, value):
        raise ProtocolError("response_invalid")
    try:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ProtocolError("response_invalid") from None
    return text.encode("utf-8") + b"\n"


def decode_response(verb: str, raw: bytes) -> PlacementResponseMessage:
    """A client's strict decoder for one response line (the trailing LF is required)."""
    definition = _RESPONSE_DEFS.get(verb) if isinstance(verb, str) else None
    if definition is None:
        raise ProtocolError("verb_unknown")
    if not isinstance(raw, (bytes, bytearray)) or not bytes(raw).endswith(b"\n"):
        raise ProtocolError("input_trailing_data")
    value = _load_object(bytes(raw)[:-1])
    if not _valid(definition, value):
        raise ProtocolError("schema_invalid")
    try:
        return _RESPONSE_RECORDS[verb].from_json(value)
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("schema_invalid") from None


@lru_cache(maxsize=1)
def result_codes() -> frozenset[str]:
    """``$defs.ResultCode``: every coordinator error code and placement code."""
    definitions = _schema_document()["$defs"]
    return frozenset(definitions["CoordinatorErrorCode"]["enum"]) | frozenset(
        definitions["PlacementCode"]["enum"])


@lru_cache(maxsize=1)
def placement_codes() -> frozenset[str]:
    """``$defs.PlacementCode``."""
    return frozenset(_schema_document()["$defs"]["PlacementCode"]["enum"])


@lru_cache(maxsize=1)
def admission_reasons() -> frozenset[str]:
    """``$defs.AdmissionReason``."""
    return frozenset(_schema_document()["$defs"]["AdmissionReason"]["enum"])


_EXIT_CLASSES: Mapping[tuple[type, str], int] = MappingProxyType({
    (ReserveResponse, "admitted"): 0, (ReserveResponse, "at_capacity"): 10,
    (ReserveResponse, "refused"): 10, (ReserveResponse, "unreachable"): 10,
    (ReserveResponse, "timeout"): 20,
    (ReleaseResponse, "released"): 0, (ReleaseResponse, "unknown_reservation"): 10,
    (ReleaseResponse, "rejected"): 10, (ReleaseResponse, "cleanup_pending"): 20,
    (ReapResponse, "complete"): 0, (ReapResponse, "cleanup_pending"): 20,
})


def exit_class(message: PlacementResponseMessage) -> int:
    """``x-cli.exit_codes`` for a schema-valid outcome: 0 settled, 10 nothing created or
    nothing held, 20 an effect may remain."""
    if isinstance(message, VersionResponse):
        return 0
    key = (type(message), message.outcome if isinstance(message, ReserveResponse) else message.state)
    try:
        return _EXIT_CLASSES[key]
    except KeyError:
        raise ProtocolError("response_invalid") from None


def validate_message(definition: str, value: object) -> bool:
    """Whether ``value`` validates against ``$defs.<definition>`` of the packaged schema."""
    return _valid(definition, value)
