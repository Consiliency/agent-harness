"""Public v2 JSON domain and RFC 8785 codec; decoding grants no launch authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import math
from types import MappingProxyType

import rfc8785

from .supervised_contracts import ContractBundle, ContractError, _v2_json, validate_record


@dataclass(frozen=True, slots=True)
class ParsedV2:
    value: object
    raw: bytes


@dataclass(frozen=True, slots=True)
class V2Envelope:
    value: Mapping
    raw: bytes
    raw_digest: str
    public_digest: str


@dataclass(frozen=True, slots=True)
class V2Decision:
    admitted: bool
    diagnostics: tuple[str, ...]


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _plain(value):
    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError()
            key.encode("utf-8")
            result[key] = _plain(child)
        return result
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if type(value) is str:
        value.encode("utf-8")
    elif type(value) in (int, float):
        if not math.isfinite(value) or (value == int(value) and abs(value) > 9007199254740991):
            raise ValueError()
    elif value is not None and type(value) is not bool:
        raise ValueError()
    return value


def canonicalize_v2(value) -> bytes:
    failed = False
    try:
        result = rfc8785.dumps(_plain(value))
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        failed = True
    if failed:
        raise ContractError("record_json_invalid") from None
    return result


def parse_v2(raw: bytes) -> ParsedV2:
    value = _v2_json(raw)
    return ParsedV2(_freeze(value), raw)


def decode_v2(raw: bytes, *, bundle: ContractBundle) -> V2Envelope:
    parsed = parse_v2(raw)
    validate_record(bundle, "admitted_launch_envelope.v2", raw)
    payload = {key: child for key, child in parsed.value.items() if key != "envelope_digest"}
    return V2Envelope(parsed.value, raw, sha256(raw).hexdigest(), sha256(canonicalize_v2(payload)).hexdigest())
