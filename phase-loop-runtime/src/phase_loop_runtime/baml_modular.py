from __future__ import annotations

import atexit
import collections
import contextlib
import hashlib
import itertools
import json
import logging
import os
import queue
import re
import site
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import weakref
import _thread
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

# Imported here, never on a calling thread: importing the worker module has no
# side effects, and it single-sources the fingerprint the worker echoes.
from ._baml_worker import fingerprint as _fingerprint


class BamlValidationError(ValueError):
    """Local, redacted BAML validation failure."""


class PhaseLoopCloseoutV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminal_status: str
    verification_status: Literal["not_run", "passed", "failed", "blocked"]
    dirty_paths: list[str]
    produced_if_gates: list[str]
    next_action: str | None = None
    blocker_class: str | None = None
    blocker_summary: str | None = None
    human_required: bool | None = None
    required_human_inputs: list[str]
    visual_evidence_path: str | None = None
    visual_evidence_non_black_pixels: int | None = None
    visual_evidence_pixel_min: int | None = None
    visual_evidence_pixel_max: int | None = None
    visual_evidence_opt_out: str | None = None
    visual_render_declared: bool | None = None

    @field_validator("terminal_status")
    @classmethod
    def _terminal_status_literal(cls, value: str) -> str:
        PHASE_STATUSES = _enum_literals("terminal_status")
        if value not in PHASE_STATUSES:
            raise ValueError(f"invalid terminal_status: {value}")
        return value

    @field_validator("blocker_class")
    @classmethod
    def _blocker_class_literal(cls, value: str | None) -> str | None:
        BLOCKER_CLASSES = _enum_literals("blocker_class")
        if value is not None and value not in (*BLOCKER_CLASSES, "none"):
            raise ValueError(f"invalid blocker_class: {value}")
        return value

    @field_validator("produced_if_gates")
    @classmethod
    def _complete_requires_gates(cls, value: list[str], info) -> list[str]:
        if info.data.get("terminal_status") == "complete" and not value:
            raise ValueError("completed closeout reported zero produced_if_gates")
        return value


@dataclass(frozen=True)
class BamlRequest:
    id: str | None
    url: str
    method: str
    headers: dict[str, str]
    body: dict[str, Any]
    prompt: str


@dataclass(frozen=True)
class ParsedResponse:
    function_name: str
    payload: dict[str, Any]
    value: Any


def build_baml_request(function_name: str, payload: dict[str, Any] | None = None) -> BamlRequest:
    if os.getpid() != _CLIENT.owner_pid:
        raise BamlWorkerError("forked", "BAML is not usable in a forked child that has not exec'd")
    bridge = _BRIDGE_TABLE.get(function_name)
    if bridge is None:
        raise BamlValidationError(f"BAML function not found: {function_name}")
    op, params = bridge
    args = _bridge_args(function_name, params, payload or {})
    outcome, request = _worker_call(op, args)
    with _client_boundary():
        return _build_from_reply(function_name, request)


def _build_from_reply(function_name: str, request: dict[str, Any]) -> BamlRequest:
    body = request["body"]
    headers = request.get("headers") or {}
    prompt = _extract_prompt(body)
    if function_name == "EmitPhaseCloseout":
        # D1a: the schema description stays byte-identical to v0's tail, so
        # schema_sha256 and the injection.py marker cut keep working.
        prompt = prompt + "\n\n" + _render_schema_description(export_function_schema("EmitPhaseCloseout"))
        messages = body.get("messages") or []
        if len(messages) != 1 or not isinstance(messages[0], dict) or not isinstance(messages[0].get("content"), str):
            raise BamlWorkerError("framing", "closeout request does not carry exactly one text message")
        body["messages"][0]["content"] = prompt
    return BamlRequest(
        id=None,
        url=str(request.get("url")),
        method=str(request.get("method")),
        headers={str(key): str(value) for key, value in dict(headers).items()},
        body=body,
        prompt=prompt,
    )


def parse_baml_response(function_name: str, raw_text: str) -> ParsedResponse:
    if _is_class_name(function_name):
        with _client_boundary(worker=False):
            schema = export_function_schema(function_name)
            payload = _find_json_payload(str(raw_text or ""))
            _validate_payload_against_schema(payload, schema)
            return ParsedResponse(function_name=function_name, payload=payload, value=payload)

    if os.getpid() != _CLIENT.owner_pid:
        raise BamlWorkerError("forked", "BAML is not usable in a forked child that has not exec'd")
    if function_name != "EmitPhaseCloseout":
        raise BamlValidationError(f"BAML function not found: {function_name}")
    outcome, value = _worker_call("parse_closeout", {"raw": str(raw_text or "")})
    with _client_boundary():
        if outcome == "error":
            raise BamlValidationError(_sanitize_text(value))
        try:
            typed = PhaseLoopCloseoutV1.model_validate(value)
        except ValidationError as exc:
            _raise_baml_validation_error(exc)
        return ParsedResponse(function_name=function_name, payload=typed.model_dump(), value=typed)


@contextlib.contextmanager
def _client_boundary(*, worker: bool = True):
    """I7 past the reply: processing a worker reply is client machinery too.
    Content errors (``BamlValidationError``) stay plain, any other ``Exception``
    becomes ``kind="fault"``, and a non-``Exception`` (an interrupt) is never
    mapped.  ``worker=False`` is the class-name branch, which never reaches the
    worker: still ``kind="fault"`` (fail closed), but not reported as one."""
    try:
        yield
    except BamlValidationError:
        raise
    except Exception as exc:
        where = "BAML client failure" if worker else "BAML response processing failure (no worker involved)"
        raise BamlWorkerError("fault", f"{where}: {_sanitize_error(exc)}") from exc


def _bridge_args(function_name: str, params: tuple[str, ...], payload: dict[str, Any]) -> dict[str, Any]:
    """Filter the payload to the bridge signature (#7), require it (#8), normalize it (#9)."""
    if not isinstance(payload, dict):
        raise BamlValidationError(f"BAML payload for {function_name} must be an object")
    if function_name == "EmitPhaseCloseout":
        # v0 rendered the closeout prompt in Python from payload.get(...) with
        # these defaults; the normalization keeps every v0-accepted payload valid.
        sha = payload.get("closeout_commit_sha")
        lists = {}
        for name in ("plan_produces", "plan_owned_files"):
            value = payload.get(name) or []
            if not isinstance(value, (list, tuple)):
                # A bad payload shape is a content error (Opus round 3 N1).
                raise BamlValidationError(f"BAML payload field {function_name}.{name} must be a list")
            lists[name] = [str(item) for item in value]
        return {
            "phase_alias": str(payload.get("phase_alias") or ""),
            "plan_produces": lists["plan_produces"],
            "plan_owned_files": lists["plan_owned_files"],
            "closeout_commit_sha": str(sha) if sha else None,
        }
    missing = [name for name in params if name not in payload]
    if missing:
        raise BamlValidationError(f"BAML payload for {function_name} is missing: {', '.join(missing)}")
    args: dict[str, Any] = {}
    for name in params:
        value = payload[name]
        if not isinstance(value, str):
            raise BamlValidationError(f"BAML payload field {function_name}.{name} must be a string")
        args[name] = value
    return args


def export_function_schema(function_name: str) -> dict[str, Any]:
    baml_files = _snapshot_files()
    baml_text = "\n".join(baml_files.values())
    return_type = _export_target_type(baml_text, function_name)
    fields = _class_fields(baml_text, return_type)
    enum_literals = _enum_literal_map()
    required = _required_fields(return_type, fields)
    properties = {
        field_name: _schema_for_baml_field(baml_text, field_name, field_type, optional, enum_literals, seen=(return_type,))
        for field_name, field_type, optional in fields
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PhaseLoopNativeCloseout" if return_type == "PhaseLoopCloseoutV1" else return_type,
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def inject_schema_description(prompt: str, schema: dict[str, Any]) -> str:
    rendered = _render_schema_description(schema)
    body = str(prompt or "").strip()
    return f"{rendered}\n\n{body}" if body else rendered


def render_baml_prompt(prompt_template: str, context_constants: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        expression = match.group("expression").strip()
        name_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)", expression)
        join_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*\|\s*join\((['\"])(.*?)\2\)", expression)
        if join_match:
            name = join_match.group(1)
            if name not in context_constants:
                if _is_taxonomy_constant(name):
                    raise BamlValidationError(f"BAML prompt taxonomy constant not found: {name}")
                return match.group(0)
            value = context_constants[name]
            if not isinstance(value, (list, tuple)):
                raise BamlValidationError(f"BAML prompt taxonomy constant is not joinable: {name}")
            return join_match.group(3).join(str(item) for item in value)
        if name_match:
            name = name_match.group(1)
            if name not in context_constants:
                if _is_taxonomy_constant(name):
                    raise BamlValidationError(f"BAML prompt taxonomy constant not found: {name}")
                return match.group(0)
            return str(context_constants[name])
        return match.group(0)

    return re.sub(r"\{\{\s*(?P<expression>.*?)\s*\}\}", replace, str(prompt_template or ""))


def _read_raw_baml_files() -> dict[str, str]:
    """The raw-read seam: every packaged ``.baml`` source, by file name."""
    src_dir = _baml_src_dir()
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(src_dir.glob("*.baml")) if path.is_file()}


def _read_baml_files() -> dict[str, str]:
    """Render the taxonomy placeholders; fail closed on any template syntax left over."""
    context_constants = _baml_prompt_context_constants()
    rendered = {name: render_baml_prompt(text, context_constants) for name, text in _read_raw_baml_files().items()}
    for name, text in rendered.items():
        if "{{" in text or "{%" in text:
            raise BamlValidationError(f"BAML source {name} still contains template syntax after rendering")
    return rendered


def _snapshot_files() -> dict[str, str]:
    """The per-process source snapshot shared by the worker and the regex readers (#29)."""
    return _CLIENT.files()[0]


def _baml_prompt_context_constants() -> dict[str, tuple[str, ...]]:
    from . import models

    return {
        "allowed_terminal_statuses": tuple(models.PHASE_STATUSES),
        "allowed_verification_statuses": ("not_run", "passed", "failed", "blocked"),
        "allowed_blocker_classes": (*models.BLOCKER_CLASSES, "none"),
    }


def _is_taxonomy_constant(name: str) -> bool:
    return name in {"allowed_terminal_statuses", "allowed_verification_statuses", "allowed_blocker_classes"}


def _baml_src_dir() -> Path:
    # Primary: the packaged baml_src shipped as package-data inside
    # phase_loop_runtime, resolved via importlib.resources so it travels in the
    # wheel regardless of installer (DECOUPLE SL-0/SL-2). The legacy candidates
    # are kept as a fallback for editable/source layouts and the old data-files
    # share/ install, but resolution no longer depends on a repo-relative walk.
    from .runtime_resources import package_root

    root = package_root()
    if root is not None:
        packaged = root / "baml_src"
        if (packaged / "emit_phase_closeout.baml").is_file():
            return packaged
    candidates = [
        # In-package source/editable layout (the same dir importlib.resources
        # resolves once installed). The old repo-root vendor/.../baml_src candidate
        # was removed in DECOUPLE -- that path no longer exists after the move.
        Path(__file__).resolve().parent / "baml_src",
        Path(sysconfig.get_paths().get("data", "")) / "share" / "phase-loop-runtime" / "baml_src",
        Path(site.USER_BASE) / "share" / "phase-loop-runtime" / "baml_src",
        Path(__file__).resolve().parents[4] / "share" / "phase-loop-runtime" / "baml_src",
    ]
    for candidate in candidates:
        if (candidate / "emit_phase_closeout.baml").exists():
            return candidate
    raise BamlValidationError("BAML source file not found: emit_phase_closeout.baml")


def _function_return_type(baml_text: str, function_name: str) -> str:
    match = re.search(rf"\bfunction\s+{re.escape(function_name)}\s*\([^)]*\)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{{", baml_text, re.DOTALL)
    if not match:
        raise BamlValidationError(f"BAML function not found: {function_name}")
    return match.group(1)


def _export_target_type(baml_text: str, name: str) -> str:
    try:
        return _function_return_type(baml_text, name)
    except BamlValidationError:
        if _class_exists(baml_text, name):
            return name
        raise


def _is_class_name(name: str) -> bool:
    return _class_exists("\n".join(_snapshot_files().values()), name)


def _class_exists(baml_text: str, class_name: str) -> bool:
    return bool(re.search(rf"\bclass\s+{re.escape(class_name)}\s*\{{", baml_text))


def _class_fields(baml_text: str, class_name: str) -> list[tuple[str, str, bool]]:
    match = re.search(rf"\bclass\s+{re.escape(class_name)}\s*\{{(?P<body>.*?)\n\}}", baml_text, re.DOTALL)
    if not match:
        raise BamlValidationError(f"BAML class not found: {class_name}")
    fields: list[tuple[str, str, bool]] = []
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        # D3 (agent-harness#1135): accept both the v1 ``name: type,`` form and the
        # legacy ``name type`` form; anything else still fails loudly below.
        field_match = re.fullmatch(r"([A-Za-z_]\w*)(?:\s*:\s*|\s+)([A-Za-z_]\w*(?:\[\])?)(\?)?\s*,?", line)
        if not field_match:
            raise BamlValidationError(f"unsupported BAML class field syntax in {class_name}: {line}")
        fields.append((field_match.group(1), field_match.group(2), bool(field_match.group(3))))
    if not fields:
        raise BamlValidationError(f"BAML class has no exportable fields: {class_name}")
    return fields


@lru_cache(maxsize=1)
def _enum_literal_map() -> dict[str, tuple[str, ...]]:
    baml_text = "\n".join(_snapshot_files().values())
    result: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in baml_text.splitlines():
        line = raw_line.strip()
        header = re.fullmatch(r"//\s*([A-Za-z_][A-Za-z0-9_]*)\s+enum literals:\s*(.*)", line)
        if header:
            current = header.group(1)
            result[current] = []
            _extend_enum_literals(result[current], header.group(2))
            continue
        if current and line.startswith("//"):
            content = line[2:].strip()
            if " enum literals:" in content:
                current = None
                continue
            _extend_enum_literals(result[current], content)
            continue
        if current and line and not line.startswith("//"):
            current = None
    from . import models

    result["terminal_status"] = list(models.PHASE_STATUSES)
    result["verification_status"] = ["not_run", "passed", "failed", "blocked"]
    result["blocker_class"] = [*models.BLOCKER_CLASSES, "none"]
    return {key: tuple(values) for key, values in result.items()}


def _extend_enum_literals(values: list[str], text: str) -> None:
    for item in text.split(","):
        literal = item.strip().strip("`.")
        if literal:
            values.append(literal)


def _enum_literals(field_name: str) -> tuple[str, ...]:
    values = _enum_literal_map().get(field_name)
    if not values:
        raise BamlValidationError(f"BAML enum literals not found for field: {field_name}")
    return values


def _schema_for_baml_field(
    baml_text: str,
    field_name: str,
    field_type: str,
    optional: bool,
    enum_literals: dict[str, tuple[str, ...]],
    *,
    seen: tuple[str, ...],
) -> dict[str, Any]:
    array_item_type = field_type[:-2] if field_type.endswith("[]") else None
    if field_type == "string":
        schema: dict[str, Any] = {"type": ["string", "null"] if optional else "string"}
    elif field_type == "bool":
        schema = {"type": ["boolean", "null"] if optional else "boolean"}
    elif field_type == "float":
        schema = {"type": ["number", "null"] if optional else "number"}
    elif field_type == "int":
        schema = {"type": ["integer", "null"] if optional else "integer"}
    elif array_item_type == "string":
        if optional:
            schema = {"type": ["array", "null"], "items": {"type": "string"}}
        else:
            schema = {"type": "array", "items": {"type": "string"}}
    elif array_item_type and _class_exists(baml_text, array_item_type):
        item_schema = _schema_for_baml_class(baml_text, array_item_type, enum_literals, seen=seen)
        if optional:
            schema = {"type": ["array", "null"], "items": item_schema}
        else:
            schema = {"type": "array", "items": item_schema}
    elif _class_exists(baml_text, field_type):
        object_schema = _schema_for_baml_class(baml_text, field_type, enum_literals, seen=seen)
        if optional:
            schema = {**object_schema, "type": ["object", "null"]}
        else:
            schema = object_schema
    else:
        raise BamlValidationError(f"unsupported BAML field type for schema export: {field_type}")
    if field_name in enum_literals:
        enum_values: list[str | None] = list(enum_literals[field_name])
        if optional:
            enum_values.append(None)
        schema["enum"] = enum_values
    description = _FIELD_DESCRIPTIONS.get(field_name)
    if description:
        schema["description"] = description
    return schema


def _schema_for_baml_class(
    baml_text: str,
    class_name: str,
    enum_literals: dict[str, tuple[str, ...]],
    *,
    seen: tuple[str, ...],
) -> dict[str, Any]:
    if class_name in seen:
        raise BamlValidationError(f"recursive BAML class export is unsupported: {class_name}")
    fields = _class_fields(baml_text, class_name)
    required = _required_fields(class_name, fields)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            field_name: _schema_for_baml_field(
                baml_text,
                field_name,
                field_type,
                optional,
                enum_literals,
                seen=(*seen, class_name),
            )
            for field_name, field_type, optional in fields
        },
    }


def _required_fields(class_name: str, fields: list[tuple[str, str, bool]]) -> list[str]:
    if class_name == "PhaseLoopCloseoutV1":
        return [field_name for field_name, _field_type, _optional in fields]
    return [field_name for field_name, _field_type, optional in fields if not optional]


def _validate_payload_against_schema(payload: Any, schema: dict[str, Any], path: str = "$") -> None:
    allowed_type = schema.get("type")
    if isinstance(allowed_type, list) and payload is None and "null" in allowed_type:
        return
    effective_type = next((item for item in allowed_type if item != "null"), None) if isinstance(allowed_type, list) else allowed_type
    if effective_type == "object":
        if not isinstance(payload, dict):
            raise BamlValidationError(f"{path} must be an object")
        required = set(schema.get("required", ()))
        missing = required.difference(payload)
        extra = set(payload).difference(schema.get("properties", {}))
        if missing:
            raise BamlValidationError(f"{path} missing required fields: {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False and extra:
            raise BamlValidationError(f"{path} has unsupported fields: {', '.join(sorted(extra))}")
        for field_name, field_schema in schema.get("properties", {}).items():
            if field_name in payload:
                _validate_payload_against_schema(payload[field_name], field_schema, f"{path}.{field_name}")
    elif effective_type == "array":
        if not isinstance(payload, list):
            raise BamlValidationError(f"{path} must be an array")
        for index, item in enumerate(payload):
            _validate_payload_against_schema(item, schema.get("items", {}), f"{path}[{index}]")
    elif effective_type == "string":
        if not isinstance(payload, str):
            raise BamlValidationError(f"{path} must be a string")
    elif effective_type == "boolean":
        if not isinstance(payload, bool):
            raise BamlValidationError(f"{path} must be a boolean")
    elif effective_type == "number":
        # JSON Schema "number" accepts both int and float (but rejects bool which subclasses int in Python)
        if not isinstance(payload, (int, float)) or isinstance(payload, bool):
            raise BamlValidationError(f"{path} must be a number")
    elif effective_type == "integer":
        if not isinstance(payload, int) or isinstance(payload, bool):
            raise BamlValidationError(f"{path} must be an integer")
    else:
        raise BamlValidationError(f"{path} has unsupported schema type: {allowed_type}")
    if "enum" in schema and payload not in schema["enum"]:
        raise BamlValidationError(f"{path} has unsupported literal")


_FIELD_DESCRIPTIONS = {
    "terminal_status": "Final phase status claimed by the executor closeout.",
    "verification_status": "Verification outcome for the reported phase work.",
    "dirty_paths": "Repo-relative dirty paths left after execution.",
    "produced_if_gates": "Interface-freeze gates actually produced by this closeout.",
    "next_action": "Concise next action for the operator or runner. May be null.",
    "blocker_class": "Frozen blocker class when terminal_status is blocked. Null otherwise.",
    "blocker_summary": "Actionable non-secret blocker summary. Null when not blocked.",
    "human_required": "Whether the blocker requires a human decision. Null when not blocked.",
    "required_human_inputs": "Non-secret human inputs required to unblock execution. Empty when not blocked.",
}


def _render_schema_description(schema: dict[str, Any]) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    lines = [
        "Phase-loop closeout JSON schema description:",
        f"schema_sha256: {hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
        f"type: {schema.get('type')}",
        f"additionalProperties: {json.dumps(schema.get('additionalProperties'))}",
        "required: " + ", ".join(str(field) for field in schema.get("required", ())),
        "properties:",
    ]
    for field_name in schema.get("required", ()):
        field_schema = schema.get("properties", {}).get(field_name, {})
        line = f"- {field_name}: type={json.dumps(field_schema.get('type'), sort_keys=True)}"
        if "enum" in field_schema:
            line += "; enum=" + ", ".join("null" if value is None else str(value) for value in field_schema["enum"])
        if field_schema.get("items"):
            line += "; items=" + json.dumps(field_schema["items"], sort_keys=True, separators=(",", ":"))
        lines.append(line)
    return "\n".join(lines)


def _extract_prompt(body: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in body.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
        elif content is not None:
            parts.append(str(content))
    return "\n\n".join(part for part in parts if part).strip()


def _find_json_payload(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise BamlValidationError("no JSON object found in BAML response")


def _sanitize_error(exc: BaseException) -> str:
    message = str(exc)
    if isinstance(exc, ValidationError):
        message = "; ".join(error.get("msg", "validation error") for error in exc.errors())
    return _sanitize_text(message) or exc.__class__.__name__


# Redaction for every message and diagnostic this module publishes: known
# values first, then key/value patterns (corrected character class and
# replacement template), bearer values and common token shapes.
_SECRET_KV_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|token|secret|password|passwd|credential)[\w-]*"
    r"(?P<value>[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?[^\s,;\"']*|\s+bearer\s+[^\s,;\"']*)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;\"']+")
_TOKEN_SHAPES_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})"
)
_SECRET_ENV_NAME_RE = re.compile(r"(?i)(key|token|secret|passw|credential|auth)")


def _known_secret_values() -> list[str]:
    """Exact values to redact first: this process's environment variables whose
    names look secret (the patterns below are the backup)."""
    values = {value for name, value in os.environ.items() if _SECRET_ENV_NAME_RE.search(name) and len(value) >= 8}
    return sorted(values, key=len, reverse=True)


def _redact_secrets(text: str) -> str:
    for value in _known_secret_values():
        text = text.replace(value, "<redacted>")
    text = _SECRET_KV_RE.sub(lambda m: m.group(1) + "=<redacted>", text)  # a key WITH a value only
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    return _TOKEN_SHAPES_RE.sub("<redacted>", text)


def _sanitize_text(message: str) -> str:
    message = _redact_secrets(message)
    message = " ".join(message.split())
    if len(message) > 500:
        message = message[:497] + "..."
    return message or "BAML validation failed"


def _raise_baml_validation_error(exc: BaseException) -> None:
    raise BamlValidationError(_sanitize_error(exc)) from exc


# ---------------------------------------------------------------------------
# BAML v1 worker client (agent-harness#1135).
#
# The v1 runtime is a process-global native singleton with its own exit hooks,
# so it never runs in this process: it runs in ``_baml_worker.py``, a
# dedicated subprocess.  The client below is specified by invariants I1-I9 of
# the migration plan (``.consiliency/plans/detailed-baml-v1-migration-*.md``);
# ``tests/test_phase_loop_baml_v1_runtime.py`` holds their falsifiers.
#
# Design:
# - One lifecycle OWNER thread (``_Client._own``) performs every transition
#   and every disposal.  Exactly one owner runs at a time: a thread becomes
#   the owner only by taking the single baton out of ``_Client.baton`` (a
#   ``SimpleQueue`` holding one token), and it puts the baton back when it
#   exits.  Extra candidate threads find the queue empty and exit at once.
# - The CALLING thread never takes a lock.  It does C-atomic ``SimpleQueue``
#   puts and timed gets, and stamps ``_Request.heartbeat`` while it waits.  A
#   ``BaseException`` on the calling thread sends one abandonment notice and is
#   re-raised unchanged.  If that notice is lost, the owner's backstop
#   abandons a request whose heartbeat is older than ``abandon_grace_s``.
# - One long-lived SPAWNER thread runs every ``Popen``, because Linux
#   PR_SET_PDEATHSIG fires when the forking *thread* exits.
# - Per generation, a READER thread owns the worker's stdout fd and a WRITER
#   thread owns its stdin fd; each closes its fd when it stops.
# - RECOVERY NEVER WAITS FOR A FUTURE API CALL (codex round 3).  An exception
#   that unwinds an owner transition is caught by the owner itself, which runs
#   recovery on the same thread at once and resumes its loop.  As a backstop,
#   for an owner thread that exits anyway (its handler died too, or it gave up
#   after repeated failures without progress), a SUPERVISOR thread relaunches
#   an owner within ``_SUPERVISE_S`` whenever recovery or cleanup is pending.
# - Daemon threads never log.  Owner-side notes go to ``_Client.pending``,
#   which the calling thread drains lock-free on its next call.
# ---------------------------------------------------------------------------

_REQUEST_CAP = 4 * 1024 * 1024  # serialized request body bytes (#27)
_ENVELOPE_ALLOWANCE = 1024
_RESPONSE_CAP = 17 * 1024 * 1024  # derived from the request cap (#27)
_ATTEMPT_DEADLINE_S = 60.0
_MAX_RETRIES = 2
_QUEUE_BUDGET_S = (_MAX_RETRIES + 1) * _ATTEMPT_DEADLINE_S + 10.0
_REAP_BOUND_S = 2.0
# I1 backstop: a request whose caller stopped stamping its heartbeat for this
# long is abandoned without a notice.  Disposal then finishes within
# ``abandon_grace_s + _REAP_BOUND_S`` of the last heartbeat.
_ABANDON_GRACE_S = 5.0
_HEARTBEAT_S = 0.1
_OWNER_TICK_S = 0.05
_OWNER_IDLE_TICK_S = 0.5
_OWNER_STALE_S = 2.0
_OWNER_LAUNCH_BUCKET_S = 0.25
_OWNER_REENTRIES = 3  # in-thread recoveries in a row without loop progress before the owner exits
_SUPERVISE_S = 0.25  # backstop: an exited owner with pending work is relaunched this fast
_EXIT_GRACE_S = 4.5  # atexit: graceful EOF wait before kill; the whole exit stays under 5 s
_EOF_RC_WAIT_S = 0.5

_WORKER_KINDS = frozenset(
    {"spawn", "init_fault", "died", "timeout", "desync", "framing", "fingerprint", "fault", "busy", "forked", "shutdown"}
)
# Transport and liveness faults are retried on a fresh worker; content-like
# faults (init_fault, fault, fingerprint) are deterministic and are not.
_RETRYABLE_KINDS = frozenset({"spawn", "died", "timeout", "desync", "framing"})
_WORKER_ENV_KEYS = ("SYSTEMROOT", "WINDIR", "TMPDIR", "TMP", "TEMP")
_WORKER_LOADER_KEYS = {
    "linux": ("LD_LIBRARY_PATH",),
    "darwin": ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"),
}

# Bridge table (#23): the only functions that reach the worker.
_BRIDGE_TABLE: dict[str, tuple[str, tuple[str, ...]]] = {
    "EmitPhaseCloseout": ("closeout_request", ("phase_alias", "plan_produces", "plan_owned_files", "closeout_commit_sha")),
    "EvaluateSuspectedFakeEvidence": (
        "evidence_request",
        ("tier2_signal_summary", "sample_artifact_content", "expected_artifact_characteristics"),
    ),
}


class BamlWorkerError(BamlValidationError):
    """The BAML worker could not answer: a transport, liveness or lifecycle fault.

    ``kind`` is one of ``spawn``, ``init_fault``, ``died``, ``timeout``,
    ``desync``, ``framing``, ``fingerprint``, ``fault``, ``busy``, ``forked``,
    ``shutdown``.  ``rc`` is set only when the worker is known to be dead.
    Callers treat it as "not evaluated", never as a verdict on content.

    ``kind="fault"`` also covers a non-content failure of the client's own
    machinery, including the class-name parse branch, which never reaches the
    worker: I7 types it and fails closed rather than letting it escape.
    """

    def __init__(self, kind: str, message: str = "", rc: int | None = None) -> None:
        self.kind = kind
        self.rc = rc
        super().__init__(message or f"BAML worker {kind}" + (f" (rc={rc})" if rc is not None else ""))

    def __reduce__(self):
        return (type(self), (self.kind, str(self), self.rc))


def worker_fault_log() -> list[dict[str, Any]]:
    """Every worker disposal and idle death recorded by this process, oldest first."""
    return list(_CLIENT.fault_log)


class _Request:
    __slots__ = (
        "op", "body", "files", "fp", "reply", "enqueued_at", "started_at", "heartbeat",
        "attempts", "attempt_deadline", "done", "consumed", "gen", "spawn", "outcome",
    )

    def __init__(self, op: str, body: bytes, files: dict[str, str], fp: str) -> None:
        self.op = op
        self.body = body
        self.files = files
        self.fp = fp
        self.reply: queue.SimpleQueue = queue.SimpleQueue()
        now = time.monotonic()
        self.enqueued_at = now
        self.heartbeat = now
        self.started_at: float | None = None
        self.attempts = 0
        self.attempt_deadline = 0.0
        self.done = False
        self.consumed = False
        self.outcome: tuple[str, Any] | None = None
        self.gen: _Gen | None = None
        self.spawn: _Spawn | None = None


class _Spawn:
    __slots__ = ("token", "retired", "files", "fp", "requested_at")

    def __init__(self, token: int, files: dict[str, str], fp: str) -> None:
        self.token = token
        self.retired = False
        self.files = files
        self.fp = fp
        self.requested_at = time.monotonic()


class _Baton:
    """The single owner baton (see ``_Client.__init__``)."""

    __slots__ = ("__weakref__",)


class _Gen:
    """One worker process and its helper threads."""

    def __init__(self, number: int, proc: subprocess.Popen, read_fd: int, write_fd: int, err_file, fp: str, job: Any) -> None:
        self.number = number
        self.proc = proc
        self.pid = proc.pid
        self.read_fd = read_fd
        self.write_fd = write_fd
        self.err_file = err_file
        self.fp = fp
        self.job = job
        self.writes: queue.SimpleQueue = queue.SimpleQueue()
        self.state = "new"  # new -> init -> idle <-> busy -> dying -> disposed
        self.pending_id: int | None = None
        self.request: _Request | None = None
        self.dying_since = 0.0
        self.killed_at: float | None = None
        self.eof_state = ""
        self.threads: list[threading.Thread] = []
        self.eof_partial = False
        self.overdue = False
        self.log_entry: dict[str, Any] | None = None


_STDERR_TAIL_BYTES = 2048


def _stderr_tail(err_file) -> str:
    try:
        if err_file.closed:
            return ""
        size = err_file.seek(0, os.SEEK_END)
        err_file.seek(max(0, size - _STDERR_TAIL_BYTES))
        data = err_file.read(_STDERR_TAIL_BYTES)
    except (OSError, ValueError):
        return ""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    return _sanitize_text(text) if text.strip() else ""


def _exiting(proc: subprocess.Popen) -> bool:
    """Whether the worker has observably died: reaped, or (Linux) its leader
    thread is already a zombie while the rest of the process finishes exiting."""
    if proc.poll() is not None:
        return True
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{proc.pid}/stat", "rb") as stat:
                state = stat.read().rsplit(b")", 1)[1].split()[0]
        except (OSError, IndexError):
            return True
        return state in (b"Z", b"X")
    return False


def _spawn_popen(argv: list[str], **kwargs: Any) -> subprocess.Popen:
    """The single spawn seam: every worker process starts here."""
    return subprocess.Popen(argv, **kwargs)


def _deliver(req: _Request, outcome: tuple[str, Any]) -> None:
    """The single reply seam: each request is answered exactly once, here.

    Effect before flag: the outcome is recorded and enqueued before ``done`` is
    set, so a request marked done has always had its reply put.  A surplus
    reply (recovery re-delivering, below) is harmless: the caller takes one."""
    req.outcome = outcome
    req.reply.put(outcome)
    req.done = True


def _send_abandon(client: "_Client", req: _Request) -> None:
    """The abandonment-notice seam (the calling thread's only notice path)."""
    client.events.put(("abandon", req))


def _worker_env() -> dict[str, str]:
    """The worker's whole environment (#15): an allowlist, nothing inherited wholesale."""
    env = {"PATH": os.path.dirname(_worker_interpreter())}
    keys = list(_WORKER_ENV_KEYS)
    keys.extend(_WORKER_LOADER_KEYS.get(sys.platform, ()))
    for key in keys:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


def _worker_interpreter() -> str:
    if os.name == "nt":
        # The real interpreter, not the venv redirector, so the process in the
        # Job Object is the worker itself.
        return getattr(sys, "_base_executable", None) or sys.executable
    return sys.executable


def _worker_script() -> str:
    return str(Path(__file__).resolve().parent / "_baml_worker.py")


def _worker_cwd() -> str:
    return str(Path(__file__).resolve().parent)


def _worker_sys_path() -> list[str]:
    return [entry for entry in sys.path if isinstance(entry, str) and entry and os.path.isabs(entry)]


_JOB_SEQUENCE = itertools.count(1)


class _WindowsJob:
    """A KILL_ON_JOB_CLOSE Job Object holding exactly one worker (Windows only)."""

    def __init__(self, pid_handle: int) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Explicit signatures: the ctypes default (c_int) truncates 64-bit HANDLEs.
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32
        # A per-generation name, never reused within a process: the I9 falsifier
        # proves a disposed generation's Job is gone by opening it by name, which
        # a reused numeric handle value could not prove (codex r15).
        self.name = f"phase-loop-baml-{os.getpid()}-{next(_JOB_SEQUENCE)}"
        handle = kernel32.CreateJobObjectW(None, self.name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

        class _BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        job_object_extended_limit_information = 9
        try:
            if not kernel32.SetInformationJobObject(handle, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
            if not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(pid_handle)):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        except BaseException:
            kernel32.CloseHandle(handle)
            raise
        self.handle = handle

    def close(self) -> None:
        handle, self.handle = self.handle, None
        if handle:
            self._kernel32.CloseHandle(handle)


class _Client:
    """Owner of the BAML worker for this process (one instance, ``_CLIENT``)."""

    def __init__(self, *, test_mode: bool = False, **config: Any) -> None:
        # Allocation only: no thread, no process, no file access.
        self.owner_pid = os.getpid()
        self.test_mode = test_mode
        self.deadline_s = float(config.pop("deadline_s", _ATTEMPT_DEADLINE_S))
        self.retries = int(config.pop("retries", _MAX_RETRIES))
        self.queue_budget_s = float(config.pop("queue_budget_s", (self.retries + 1) * self.deadline_s + 10.0))
        self.abandon_grace_s = float(config.pop("abandon_grace_s", _ABANDON_GRACE_S))
        self.no_pdeathsig = bool(config.pop("no_pdeathsig", False))
        if config:
            raise TypeError(f"unknown worker client options: {sorted(config)}")
        if self.no_pdeathsig and not test_mode:
            raise ValueError("no_pdeathsig requires test_mode")
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.baton: queue.SimpleQueue = queue.SimpleQueue()
        # The one baton is a weakly referenceable token.  It is referenced only
        # by this queue or by the thread holding it, so a token nobody
        # references any more was provably stranded (its holder died before
        # putting it back) and is reclaimed by the supervisor (``_reclaim_baton``).
        # A hand-back is never retried, so the failure direction is a strand,
        # never a duplicate (codex round 5).
        token = _Baton()
        self.baton_ref = weakref.ref(token)
        self.baton.put(token)
        del token
        self.spawns: queue.SimpleQueue = queue.SimpleQueue()
        self.snapshot: tuple[dict[str, str], str] | None = None
        self.fault_log: list[dict[str, Any]] = []
        self.pending: list[str] = []
        self.closing = False
        self.closed = False
        # Owner bookkeeping, read (never taken) by callers and the supervisor.
        # ``owner_launches`` is written by the launching threads (a CAS by bucket).
        self.owner_running = False
        self.owner_beat = 0.0
        self.owner_launches: dict[int, object] = {}
        self.owner_starts = 0
        self.owner_ident: int | None = None
        self.supervisor: threading.Thread | None = None
        # Owner-only state below (touched only by the thread holding the baton).
        self.recover = False
        self.backlog: collections.deque[_Request] = collections.deque()
        # Durable ownership (codex hb1 B1): every request the owner has accepted
        # stays here until its one reply is delivered, and every worker the
        # spawner started stays in ``generations`` until it is released.  A new
        # owner recovers from these, never from the transient slots alone.
        self.inflight: set[_Request] = set()
        self.generations: set[_Gen] = set()
        self.active: _Request | None = None
        self.gen: _Gen | None = None
        self.spawn: _Spawn | None = None
        self.dying: list[_Gen] = []
        self.late: list[_Gen] = []
        self.spawner: threading.Thread | None = None
        # Spawns handed to the spawner whose result the owner has not handled.
        # While one of them can still publish a worker, nothing may stop
        # watching for it (codex round 4).
        self.spawns_outstanding = 0
        self.next_frame_id = 0
        self.next_gen = 0
        self.next_token = 0
        self.stop_acks: list[queue.SimpleQueue] = []
        self.stop_graceful = False
        self.stop_started = 0.0

    # -- snapshot (lock-free: computed locally, published by one store) ------
    def files(self) -> tuple[dict[str, str], str]:
        snap = self.snapshot
        if snap is None:
            try:
                files = _read_baml_files()
                snap = (files, _fingerprint(files))
            except BamlValidationError:
                raise
            except Exception as exc:
                # I7: a failure of the client's own machinery (e.g. an unreadable
                # packaged source) is typed, never a raw OSError.
                raise BamlWorkerError("fault", f"BAML source snapshot failed: {_sanitize_error(exc)}") from exc
            self.snapshot = snap
        return snap

    # -- calling thread ------------------------------------------------------
    def call(self, op: str, args: dict[str, Any]) -> tuple[str, str]:
        if os.getpid() != self.owner_pid:
            raise BamlWorkerError("forked", "BAML is not usable in a forked child that has not exec'd")
        try:
            self._drain_pending()
            if self.closing:
                raise BamlWorkerError("shutdown", "BAML worker client is shutting down")
            body = _serialize_args(args)
            files, fp = self.files()
            req = _Request(op, body, files, fp)
        except BamlValidationError:
            raise  # content errors stay plain; BamlWorkerError passes through
        except Exception as exc:
            raise BamlWorkerError("fault", f"BAML client failure: {_sanitize_error(exc)}") from exc
        try:
            self._ensure_owner()
            self.events.put(("request", req))
            return self._wait(req)
        except BaseException as exc:
            if not req.consumed:
                _send_abandon(self, req)
            if isinstance(exc, Exception) and not isinstance(exc, BamlValidationError):
                # I7: any other caller-side Exception is kind="fault".  A
                # BaseException that is not an Exception (an interrupt) is never
                # mapped (I1).
                raise BamlWorkerError("fault", f"BAML client failure: {_sanitize_error(exc)}") from exc
            raise

    def _wait(self, req: _Request) -> tuple[str, str]:
        # An independent bound, derived from the request's own budgets: however
        # the owner fails, the caller never waits past queue + execution budget
        # plus the abandonment and reap bounds.
        limit = (
            req.enqueued_at + self.queue_budget_s + (self.retries + 1) * self.deadline_s
            + self.abandon_grace_s + _REAP_BOUND_S + _OWNER_STALE_S
        )
        get = req.reply.get
        while True:
            now = time.monotonic()
            req.heartbeat = now
            if now > limit:
                raise BamlWorkerError("timeout", "BAML request exceeded its total budget without a reply")
            try:
                outcome = get(True, _HEARTBEAT_S)
            except queue.Empty:
                if not self.owner_running:
                    self._ensure_owner()
                continue
            req.consumed = True
            status, value = outcome
            if status == "reply":
                return value
            if status == "abandoned":
                raise BamlWorkerError("timeout", "request abandoned by the client backstop")
            raise value

    def _ensure_owner(self) -> None:
        if self.owner_running and time.monotonic() - self.owner_beat < _OWNER_STALE_S:
            return
        if self.closed:
            raise BamlWorkerError("shutdown", "BAML worker client is closed")
        self._launch_owner()

    def _launch_owner(self) -> None:
        # One launch per short time bucket (a compare-and-set, never a lock).  A
        # launch that is interrupted, or a candidate that finds the baton taken,
        # costs at most one bucket before a waiter launches again.
        bucket = int(time.monotonic() / _OWNER_LAUNCH_BUCKET_S)
        # Only the current bucket matters; older tickets are dropped so a recurring
        # fault cannot grow this without bound (pop is atomic, list() is one C call).
        for old in [key for key in list(self.owner_launches) if key < bucket]:
            self.owner_launches.pop(old, None)
        mine = object()
        if self.owner_launches.setdefault(bucket, mine) is not mine:
            return
        try:
            # A raw C-level start, not threading.Thread.start: that runs Python
            # under threading's module locks, and an interrupt landing between a
            # lock's acquire and its ``with`` block would leave the lock held and
            # wedge every later thread start in the process (found by the I1 sweep).
            _thread.start_new_thread(self._own, ())
        except RuntimeError as exc:
            self.owner_launches.pop(bucket, None)
            raise BamlWorkerError("spawn", f"cannot start the BAML owner thread: {exc}") from None
        except BaseException:
            self.owner_launches.pop(bucket, None)
            raise

    def _drain_pending(self) -> None:
        pending = self.pending
        while True:
            try:
                message = pending.pop(0)
            except IndexError:
                return
            _LOG.warning("%s", message)

    # -- owner thread --------------------------------------------------------
    def _own(self) -> None:
        try:
            baton = self.baton.get_nowait()
        except queue.Empty:
            return
        self.owner_starts += 1
        self.owner_beat = time.monotonic()
        self.owner_running = True
        clean = False
        try:
            # get_ident() registers nothing: threading.current_thread() here would
            # leave a _DummyThread in threading._active for every owner ever run.
            self.owner_ident = threading.get_ident()
            failures = 0
            while True:
                beat = self.owner_beat
                try:
                    if self.recover:
                        self._recover()
                    self.recover = True
                    clean = self._loop()
                    break
                except BaseException:  # noqa: BLE001 - recover here and now, never on a future call
                    # A transition died part-way.  Recovery re-runs on this thread
                    # immediately; only repeated failures with no loop progress end
                    # the owner (the supervisor then relaunches one).
                    failures = failures + 1 if self.owner_beat == beat else 1
                    if failures > _OWNER_REENTRIES:
                        self.pending.append(
                            f"BAML worker owner gave up after {failures} in-thread recoveries without progress; "
                            "the supervisor relaunches it"
                        )
                        break
                    self.owner_starts += 1
        except BaseException:  # noqa: BLE001 - the owner must hand the baton back
            clean = False
        finally:
            try:
                self.recover = not clean
                self.owner_running = False
            finally:
                # One hand-back attempt, never retried: an exception can land
                # after the put has taken effect (CALL checks for asynchronous
                # exceptions on return), and a retry would then DUPLICATE the
                # baton (two owners).  If it lands before the put instead, the
                # baton is stranded, and ``_reclaim_baton`` recovers it once this
                # frame (the last reference to it) is gone.
                token, baton = baton, None
                try:
                    self.baton.put(token)
                except BaseException:  # noqa: BLE001 - strand, never duplicate
                    pass

    def _spawn_pending(self) -> bool:
        """True while a handed-over spawn can still publish a worker: its result
        is unhandled and either the spawner is alive or the result is queued.
        (Read in this order, so a spawner that reports and exits in between is
        still seen through the queued event.)"""
        if self.spawns_outstanding <= 0:
            return False
        spawner = self.spawner
        return (spawner is not None and spawner.is_alive()) or not self.events.empty()

    def _loop(self) -> bool:
        get = self.events.get
        while True:
            busy = self.active is not None or self.backlog or self.dying or self.late or self.spawn is not None or self.stop_acks
            try:
                event = get(True, _OWNER_TICK_S if busy else _OWNER_IDLE_TICK_S)
            except queue.Empty:
                event = None
            if event is not None:
                self._handle(event)
            self._service()
            self.owner_beat = time.monotonic()
            if (
                self.closed and not self.dying and not self.late and self.gen is None
                and not self.stop_acks and not self._spawn_pending()
            ):
                return True

    def _recover(self) -> None:
        # A previous owner died, possibly between any two of its steps.  Finish
        # everything it left behind from the durable registries: every accepted,
        # undelivered request outside the backlog gets a typed reply, and every
        # live worker is disposed of.  Terminal flags are not trusted here: the
        # effect each one stands for is checked and completed again.
        if self.spawn is not None:
            self.spawn.retired = True
            self.spawn = None
        for gen in list(self.generations):
            if gen.state != "disposed":
                if gen in self.dying:
                    self.dying.remove(gen)
                self._dispose(gen, "fault", phase="owner_death")
            else:
                # Disposed, but the kill or the release hand-off may not have happened.
                self._kill(gen)
                if gen not in self.late:
                    self.late.append(gen)
        waiting = set(self.backlog)
        for req in list(self.inflight):
            if req.done:
                if not req.consumed and req.reply.empty() and req.outcome is not None:
                    req.reply.put(req.outcome)  # done, but the put may not have landed
                self.inflight.discard(req)
            elif req not in waiting:
                req.gen = None
                req.spawn = None
                self._reply(req, ("error", BamlWorkerError("fault", "BAML worker client owner died")))
        self.active = None
        self.gen = None  # every generation above is disposed; the slot may still name one

    def _reply(self, req: _Request, outcome: tuple[str, Any]) -> None:
        """Deliver ``req``'s one reply, then forget it (the order matters: until
        the reply is out, ``inflight`` keeps the request recoverable)."""
        if not req.done:
            _deliver(req, outcome)
        self.inflight.discard(req)

    def _handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "request":
            req = event[1]
            self.inflight.add(req)
            if self.closing:
                self._reply(req, ("error", BamlWorkerError("shutdown", "BAML worker client is shutting down")))
            else:
                self.backlog.append(req)
        elif kind == "abandon":
            self._abandon(event[1])
        elif kind == "spawned":
            self.spawns_outstanding -= 1  # the worker, if any, is in ``generations`` already
            self._on_spawned(event[1], event[2])
        elif kind == "frame":
            self._on_frame(event[1], event[2])
        elif kind == "eof":
            self._on_eof(event[1], event[2])
        elif kind == "overflow":
            gen = event[1]
            if gen is self.gen:
                self._fail(gen, "framing", "worker response frame over the 17 MiB cap")
        elif kind == "write_error":
            gen = event[1]
            if gen is self.gen and gen.state in ("init", "busy"):
                self._fail(gen, "died", "worker stdin closed")
        elif kind == "stop":
            if self.closed:
                self.stop_acks.append(event[1])  # a stop is already under way
            else:
                self._begin_stop(event[1], graceful=event[2])

    def _service(self) -> None:
        now = time.monotonic()
        # Queue budget and abandoned-in-queue requests.
        if self.backlog:
            for req in list(self.backlog):
                if req.done:
                    self.backlog.remove(req)
                elif now - req.heartbeat > self.abandon_grace_s:
                    self.backlog.remove(req)
                    self._reply(req, ("abandoned", None))
                elif now - req.enqueued_at > self.queue_budget_s:
                    self.backlog.remove(req)
                    self._reply(req, ("error", BamlWorkerError("busy", "BAML worker queue budget exhausted")))
        active = self.active
        if active is not None:
            if now - active.heartbeat > self.abandon_grace_s:
                self._abandon(active)
            elif now >= active.attempt_deadline:
                self._expire(active)
        if self.active is None and self.backlog and not self.closing:
            self._start(self.backlog.popleft())
        self._reap(now)
        if self.stop_acks:
            self._continue_stop(now)
        supervisor = self.supervisor
        if supervisor is not None and not supervisor.is_alive() and (not self.closed or self._spawn_pending() or self.generations):
            try:
                self._ensure_supervisor()  # a dead backstop is recreated by this (the next) owner pass
            except Exception:  # noqa: BLE001 - retried on the next pass
                pass

    def _start(self, req: _Request) -> None:
        self.active = req
        req.started_at = time.monotonic()
        self._attempt(req)

    def _attempt(self, req: _Request) -> None:
        req.attempts += 1
        req.attempt_deadline = time.monotonic() + self.deadline_s
        gen = self.gen
        if gen is not None and gen.state == "idle":
            if not _exiting(gen.proc):
                self._send_op(gen, req)
                return
            # Died between calls: recorded by _reap once its exit status is
            # known, and never charged to this request.
            gen.eof_state = "idle"
            gen.state = "dying"
            gen.dying_since = time.monotonic()
            self.dying.append(gen)
        if gen is not None and gen.state == "dying":
            self.gen = None  # its idle death is still recorded by _reap
        self._request_spawn(req)

    def _request_spawn(self, req: _Request) -> None:
        try:
            self._ensure_spawner()
        except BaseException as exc:  # noqa: BLE001
            self._attempt_failed(req, BamlWorkerError("spawn", f"cannot start the BAML spawner thread: {_sanitize_error(exc)}"))
            return
        self.next_token += 1
        spawn = _Spawn(self.next_token, req.files, req.fp)
        self.spawn = spawn
        req.spawn = spawn
        self.spawns_outstanding += 1  # counted before it can exist
        self.spawns.put(spawn)

    def _reclaim_baton(self) -> None:
        """Replace a stranded baton: one that no queue and no thread references
        any more.  Only the supervisor calls this, so there is exactly one
        reclaimer, and a live token (queued or held) is never duplicated."""
        if self.baton_ref() is not None:
            return
        token = _Baton()
        self.baton_ref = weakref.ref(token)
        self.baton.put(token)
        self.pending.append("BAML worker owner baton was stranded by an interrupted hand-back and was reclaimed")

    def _ensure_supervisor(self) -> None:
        supervisor = self.supervisor
        if supervisor is not None and supervisor.is_alive():
            return
        supervisor = threading.Thread(target=self._supervise, name="phase-loop-baml-supervisor", daemon=True)
        supervisor.start()
        self.supervisor = supervisor

    def _supervise(self) -> None:
        """Backstop: relaunch an exited owner while recovery or cleanup is
        pending, so that none of it waits for a future API call.  It only reads
        owner state; the launch itself is the owner baton's compare-and-set."""
        try:
            while True:
                time.sleep(_SUPERVISE_S)
                if os.getpid() != self.owner_pid:
                    return
                self._reclaim_baton()
                if self.owner_running:
                    continue
                pending = (
                    self.recover or self.generations or self.inflight or self.backlog
                    or self.spawn is not None or self.stop_acks or self._spawn_pending()
                )
                if pending:
                    try:
                        self._launch_owner()
                    except Exception:  # noqa: BLE001 - no thread available now; retried next tick
                        pass
                elif self.closed:
                    return  # closed, and nothing registered or able to publish
        except BaseException:  # noqa: BLE001 - a dead supervisor is recreated by the next owner pass
            return

    def _ensure_spawner(self) -> None:
        # The supervisor exists before any worker can: it is started with the
        # spawner, which every worker comes from.
        self._ensure_supervisor()
        spawner = self.spawner
        if spawner is not None and spawner.is_alive():
            return
        spawner = threading.Thread(target=self._spawner_loop, name="phase-loop-baml-spawner", daemon=True)
        spawner.start()
        self.spawner = spawner

    def _on_spawned(self, spawn: _Spawn, result: Any) -> None:
        if spawn is not self.spawn or spawn.retired:
            if isinstance(result, _Gen) and result.state != "disposed":
                # (A generation recovery already disposed of is not logged twice.)
                self._kill(result)
                if result not in self.late:
                    self.late.append(result)
                self._log("spawn_late", result, phase="spawn")
                result.state = "disposed"
            return
        self.spawn = None
        req = self.active
        if req is not None:
            req.spawn = None
        if not isinstance(result, _Gen):
            if req is not None:
                self._attempt_failed(req, BamlWorkerError("spawn", f"BAML worker spawn failed: {_sanitize_error(result)}"))
            return
        gen = result
        self.gen = gen
        self.next_frame_id += 1
        gen.pending_id = self.next_frame_id
        gen.state = "init"
        init = {"id": gen.pending_id, "op": "init", "files": spawn.files, "sys_path": _worker_sys_path()}
        if self.test_mode:
            init["test_mode"] = True
        gen.writes.put((json.dumps(init, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii"))
        if req is not None and req.fp == gen.fp:
            gen.request = req
            req.gen = gen

    def _send_op(self, gen: _Gen, req: _Request) -> None:
        self.next_frame_id += 1
        gen.pending_id = self.next_frame_id
        gen.state = "busy"
        gen.request = req
        req.gen = gen
        frame = b'{"id":%d,"op":"%s","args":' % (gen.pending_id, req.op.encode("ascii")) + req.body + b"}\n"
        gen.writes.put(frame)

    def _on_frame(self, gen: _Gen, line: bytes) -> None:
        if gen is not self.gen or gen.state not in ("init", "busy", "idle"):
            return  # a frame from a disposed generation is never attributed to a successor
        try:
            frame = json.loads(line)
        except ValueError:
            self._fail(gen, "framing", "worker frame is not JSON")
            return
        if not isinstance(frame, dict):
            self._fail(gen, "framing", "worker frame is not a JSON object")
            return
        outcome_keys = set(frame) - {"id", "fingerprint"}
        if "id" not in frame or "fingerprint" not in frame or len(outcome_keys) != 1 or not outcome_keys <= {"ok", "error", "request", "fault"}:
            self._fail(gen, "framing", "worker frame has unexpected keys")
            return
        if gen.state == "idle" or frame["id"] != gen.pending_id:
            self._fail(gen, "desync", "worker frame id does not match the request")
            return
        (outcome,) = outcome_keys
        value = frame[outcome]
        if outcome == "fault":
            self._fail(gen, "init_fault" if gen.state == "init" else "fault", f"worker fault: {value}")
            return
        if frame["fingerprint"] != gen.fp:
            self._fail(gen, "fingerprint", "worker fingerprint does not match the source snapshot")
            return
        if gen.state == "init":
            if outcome != "ok":
                self._fail(gen, "framing", "worker init reply is not ok")
                return
            gen.state = "idle"
            gen.pending_id = None
            req = gen.request
            gen.request = None
            if req is not None and req is self.active and req.gen is gen:
                self._send_op(gen, req)
            return
        req = gen.request
        try:
            decoded = _decode_outcome(req.op if req is not None else "", outcome, value)
        except ValueError as exc:
            self._fail(gen, "framing", str(exc))
            return
        gen.state = "idle"
        gen.pending_id = None
        gen.request = None
        if req is not None and req is self.active:
            req.gen = None
            self._reply(req, ("reply", (outcome, decoded)))
            self.active = None

    def _on_eof(self, gen: _Gen, partial: bool) -> None:
        if gen is not self.gen or self.closing:
            return
        if gen.state in ("idle", "init", "busy"):
            # Wait briefly for the exit status, so the log and .rc are exact.
            gen.eof_partial = partial
            gen.eof_state = gen.state
            gen.state = "dying"
            gen.dying_since = time.monotonic()
            self.dying.append(gen)

    def _expire(self, req: _Request) -> None:
        spawn = req.spawn
        if spawn is not None and spawn is self.spawn:
            spawn.retired = True
            self.spawn = None
            req.spawn = None
            self._attempt_failed(req, BamlWorkerError("spawn", "BAML worker spawn exceeded its deadline"))
            return
        gen = req.gen
        if gen is not None and gen is self.gen and gen.state in ("init", "busy", "dying"):
            phase = "init" if gen.state == "init" else "in_flight"
            if gen in self.dying:
                self.dying.remove(gen)
            self._fail(gen, "timeout", "BAML worker call exceeded its deadline", phase=phase)
            return
        self._attempt_failed(req, BamlWorkerError("timeout", "BAML worker call exceeded its deadline"))

    def _abandon(self, req: _Request) -> None:
        if req.done:
            return
        if req in self.backlog:
            self.backlog.remove(req)
            self._reply(req, ("abandoned", None))
            return
        if req is not self.active:
            return
        spawn = req.spawn
        if spawn is not None and spawn is self.spawn:
            spawn.retired = True
            self.spawn = None
        gen = req.gen
        if gen is not None and gen is self.gen and gen.state in ("init", "busy", "dying"):
            if gen in self.dying:
                self.dying.remove(gen)
            self._dispose(gen, "abandoned", phase=gen.state)
        req.gen = None
        req.spawn = None
        self._reply(req, ("abandoned", None))
        self.active = None

    def _fail(self, gen: _Gen, kind: str, message: str, *, phase: str | None = None) -> None:
        req = gen.request if gen.request is not None and gen.request is self.active else None
        rc = gen.proc.poll()
        self._dispose(gen, kind, phase=phase or gen.state, rc=rc)
        if req is not None:
            req.gen = None
            self._attempt_failed(req, BamlWorkerError(kind, message, rc=rc))

    def _attempt_failed(self, req: _Request, error: BamlWorkerError) -> None:
        if req is not self.active or req.done:
            return
        started = req.started_at or time.monotonic()
        budget_left = (self.retries + 1) * self.deadline_s - (time.monotonic() - started)
        if error.kind in _RETRYABLE_KINDS and req.attempts <= self.retries and budget_left > 0 and not self.closing:
            self._attempt(req)
            return
        self._reply(req, ("error", error))
        self.active = None

    # -- disposal -------------------------------------------------------------
    def _dispose(self, gen: _Gen, kind: str, *, phase: str, rc: int | None = None) -> None:
        # Effects before flags: until ``state`` reads "disposed", recovery treats
        # the generation as live and disposes of it again.
        if gen.state == "disposed":
            return
        self._kill(gen)
        if gen not in self.late:
            self.late.append(gen)
        self._log(kind, gen, phase=phase, rc=rc if rc is not None else gen.proc.returncode)
        gen.request = None
        gen.state = "disposed"
        if gen is self.gen:
            self.gen = None

    def _kill(self, gen: _Gen) -> None:
        """Idempotent: safe to repeat, and it re-kills until the kill is recorded."""
        gen.writes.put(None)
        if gen.proc.returncode is None:
            try:
                gen.proc.kill()  # a no-op once Popen has reaped the process
            except OSError:
                pass
        if gen.killed_at is None:
            gen.killed_at = time.monotonic()

    def _log(self, kind: str, gen: _Gen, *, phase: str, rc: int | None = None) -> None:
        entry = {"kind": kind, "phase": phase, "pid": gen.pid, "generation": gen.number, "rc": rc}
        if gen.job is not None:
            entry["job"] = gen.job.name  # Windows: the generation's Job Object name
        gen.log_entry = entry
        self.fault_log.append(entry)
        self.pending.append(f"BAML worker pid {gen.pid} disposed: {kind} ({phase}, rc={rc})")

    def _reap(self, now: float) -> None:
        for gen in list(self.dying):
            rc = gen.proc.poll()
            if rc is not None or now - gen.dying_since > _EOF_RC_WAIT_S:
                self.dying.remove(gen)
                req = gen.request
                if gen.eof_state == "idle" or req is None or req is not self.active:
                    # Died between calls: recorded once, never charged to a request.
                    self._dispose(gen, "died", phase="idle", rc=rc)
                else:
                    kind = "framing" if gen.eof_partial else "died"
                    message = "worker closed its output mid-frame" if gen.eof_partial else "worker exited"
                    self._fail(gen, kind, message, phase="in_flight")
        for gen in list(self.late):
            # Released means REAPED (waited on), never merely marked: a process
            # that has not been waited on stays tracked, however long it takes.
            if gen.proc.poll() is not None:
                self.late.remove(gen)
                self._release(gen)
            elif gen.killed_at is None:
                self._kill(gen)  # queued for release without a kill: finish the effect
            elif now - gen.killed_at > _REAP_BOUND_S and not gen.overdue:
                # Past the reap bound and still not exited: kill again and say so
                # once, but keep it tracked until it can be waited on.
                gen.overdue = True
                try:
                    gen.proc.kill()
                except OSError:
                    pass
                self._log("reap_overdue", gen, phase="release")

    def _release(self, gen: _Gen) -> None:
        # Close first, forget last: a generation stays recoverable until its
        # resources are gone (both closes are idempotent).
        entry = gen.log_entry
        if entry is not None and "stderr_tail" not in entry:
            # The worker has been reaped, so its stderr is complete: keep a
            # bounded, sanitized tail for the operator (Opus N7).
            entry["stderr_tail"] = _stderr_tail(gen.err_file)
        try:
            gen.err_file.close()
        except OSError:
            pass
        job = gen.job
        if job is not None:
            job.close()
        self.generations.discard(gen)

    # -- stop / shutdown ------------------------------------------------------
    def _begin_stop(self, ack: queue.SimpleQueue, graceful: bool) -> None:
        self.closing = True
        self.closed = True
        self.stop_acks.append(ack)
        self.stop_graceful = graceful
        self.stop_started = time.monotonic()
        for req in list(self.backlog):
            self.backlog.remove(req)
            self._reply(req, ("error", BamlWorkerError("shutdown", "BAML worker client is shutting down")))
        for req in list(self.inflight):
            self._reply(req, ("error", BamlWorkerError("shutdown", "BAML worker client is shutting down")))
        # Requests handed over but never accepted (an inline stop, with no owner
        # running) are answered too; other queued events are moot once closing.
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "request" and not event[1].done:
                self._reply(event[1], ("error", BamlWorkerError("shutdown", "BAML worker client is shutting down")))
            elif event[0] == "stop":
                self.stop_acks.append(event[1])
            elif event[0] == "spawned":
                self.spawns_outstanding -= 1
                if isinstance(event[2], _Gen) and event[2].state != "disposed":
                    self._kill(event[2])
                    if event[2] not in self.late:
                        self.late.append(event[2])
                    event[2].state = "disposed"
        self.active = None
        if self.spawn is not None:
            self.spawn.retired = True
            self.spawn = None
        gen = self.gen
        if gen is not None:
            if graceful and gen.state == "idle":
                gen.writes.put(None)  # EOF on the worker's stdin: the graceful path
            else:
                self._stop_gen(gen)
        self.spawns.put(None)

    def _stop_gen(self, gen: _Gen) -> None:
        self._kill(gen)
        if gen not in self.late:
            self.late.append(gen)
        if gen in self.dying:
            self.dying.remove(gen)
        gen.state = "disposed"
        if gen is self.gen:
            self.gen = None

    def _continue_stop(self, now: float) -> None:
        gen = self.gen
        if gen is not None:
            if gen.proc.poll() is not None:
                gen.killed_at = gen.killed_at or now
                if gen not in self.late:
                    self.late.append(gen)
                gen.state = "disposed"
                self.gen = None
            elif now - self.stop_started > _EXIT_GRACE_S:
                self._stop_gen(gen)
        for g in list(self.dying):
            self._stop_gen(g)
        if self.gen is None and not self.late and not self._spawn_pending():
            # Never acknowledged while a spawn can still publish a worker.
            acks, self.stop_acks = self.stop_acks, []
            for ack in acks:
                ack.put(True)

    def stop(self, *, graceful: bool, timeout: float) -> None:
        """Dispose of every worker and stop the owner.  Used by atexit and reset."""
        if os.getpid() != self.owner_pid:
            return
        self.closing = True
        ack: queue.SimpleQueue = queue.SimpleQueue()
        deadline = time.monotonic() + timeout
        sent = False
        while True:
            if sent and not ack.empty():
                return
            try:
                baton = self.baton.get_nowait()
                break
            except queue.Empty:
                pass
            # An owner is running (or starting): it does the work.  If it dies
            # before acknowledging, the baton comes back and this thread finishes.
            if not sent:
                self.events.put(("stop", ack, graceful))
                sent = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                ack.get(True, min(remaining, _HEARTBEAT_S))
                return
            except queue.Empty:
                continue
        # No owner runs, so this thread may touch owner state; it starts no thread.
        try:
            if self.recover:
                try:
                    self._recover()  # idempotent; a later owner repeats it
                except Exception:  # noqa: BLE001 - never raise into atexit; the stop below still runs
                    pass
            self._begin_stop(ack, graceful)
            while self.stop_acks and time.monotonic() < deadline:
                self._service_stop_inline()
                time.sleep(_OWNER_TICK_S)
        finally:
            self.baton.put(baton)

    def _service_stop_inline(self) -> None:
        # Events keep arriving while no owner runs: a spawn that returns now is
        # handled here (retired, so killed and queued for release).
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle(event)
        now = time.monotonic()
        self._reap(now)
        self._continue_stop(now)

    # -- spawner thread -------------------------------------------------------
    def _spawner_loop(self) -> None:
        try:
            while True:
                spawn = self.spawns.get()
                if spawn is None:
                    return
                try:
                    result: Any = self._spawn_worker(spawn)
                except BaseException as exc:  # noqa: BLE001 - reported to the owner as kind="spawn"
                    result = exc
                self.events.put(("spawned", spawn, result))
        except BaseException:  # noqa: BLE001 - a dead spawner is recreated on the next spawn
            return

    def _spawn_worker(self, spawn: _Spawn) -> _Gen:
        read_in, write_in = os.pipe()
        try:
            read_out, write_out = os.pipe()
        except BaseException:
            os.close(read_in)
            os.close(write_in)
            raise
        err_file = None
        proc = None
        try:
            err_file = tempfile.TemporaryFile()
            argv = [_worker_interpreter(), "-I", "-S", _worker_script(), str(os.getpid()), ",".join(sorted(_worker_env()))]
            if self.no_pdeathsig:
                argv.append("--no-pdeathsig")
            kwargs: dict[str, Any] = {
                "stdin": read_in,
                "stdout": write_out,
                "stderr": err_file,
                "env": _worker_env(),
                "cwd": _worker_cwd(),
                "close_fds": True,
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            proc = _spawn_popen(argv, **kwargs)
        except BaseException:
            for fd in (read_in, write_in, read_out, write_out):
                os.close(fd)
            if err_file is not None:
                err_file.close()
            raise
        os.close(read_in)
        os.close(write_out)
        job = None
        gen = None
        try:
            if os.name == "nt":
                job = _WindowsJob(int(proc._handle))  # assigned before init is sent
            self.next_gen += 1
            gen = _Gen(self.next_gen, proc, read_out, write_in, err_file, spawn.fp, job)
            # Registered before anyone can lose it: an owner that dies anywhere
            # between here and publication still finds and disposes of it.
            self.generations.add(gen)
            reader = threading.Thread(target=self._reader_loop, args=(gen,), name=f"phase-loop-baml-reader-{gen.pid}", daemon=True)
            writer = threading.Thread(target=self._writer_loop, args=(gen,), name=f"phase-loop-baml-writer-{gen.pid}", daemon=True)
            gen.threads = [reader, writer]
            reader.start()
        except BaseException:
            try:
                proc.kill()
                proc.wait(_REAP_BOUND_S)
            except BaseException:  # noqa: BLE001
                pass
            if gen is not None:
                self.generations.discard(gen)
            os.close(read_out)
            os.close(write_in)
            err_file.close()
            if job is not None:
                job.close()
            raise
        try:
            writer.start()
        except BaseException:
            try:
                proc.kill()
                proc.wait(_REAP_BOUND_S)
            except BaseException:  # noqa: BLE001
                pass
            self.generations.discard(gen)
            os.close(write_in)  # the reader closes read_out on EOF
            err_file.close()
            if job is not None:
                job.close()
            raise
        return gen

    # -- per-generation helpers ----------------------------------------------
    def _reader_loop(self, gen: _Gen) -> None:
        fd = gen.read_fd
        events = self.events
        try:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    events.put(("eof", gen, size > 0))
                    return
                start = 0
                while True:
                    newline = chunk.find(b"\n", start)
                    if newline < 0:
                        break
                    piece = chunk[start:newline]
                    if size + len(piece) > _RESPONSE_CAP:
                        events.put(("overflow", gen))
                        return
                    chunks.append(piece)
                    events.put(("frame", gen, b"".join(chunks)))
                    chunks = []
                    size = 0
                    start = newline + 1
                rest = chunk[start:]
                if rest:
                    chunks.append(rest)
                    size += len(rest)
                    if size > _RESPONSE_CAP:
                        events.put(("overflow", gen))
                        return
        except BaseException:  # noqa: BLE001 - treated as the worker's output closing
            try:
                events.put(("eof", gen, True))
            except BaseException:  # noqa: BLE001
                pass
        finally:
            os.close(fd)

    def _writer_loop(self, gen: _Gen) -> None:
        fd = gen.write_fd
        get = gen.writes.get
        try:
            while True:
                data = get()
                if data is None:
                    return
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
        except BaseException:  # noqa: BLE001 - EPIPE and friends: the worker is gone
            try:
                self.events.put(("write_error", gen))
            except BaseException:  # noqa: BLE001
                pass
        finally:
            os.close(fd)


_OUTCOMES_BY_OP = {
    "parse_closeout": ("ok", "error"),
    "closeout_request": ("request",),
    "evidence_request": ("request",),
    "env": ("ok",),
}


def _decode_outcome(op: str, outcome: str, value: Any) -> Any:
    """Owner-side validation of an op reply; a ValueError is a framing fault."""
    if outcome not in _OUTCOMES_BY_OP.get(op, ()):
        raise ValueError(f"worker outcome {outcome!r} is not valid for op {op!r}")
    if op == "env":
        if not isinstance(value, dict):
            raise ValueError("worker env reply is not an object")
        return value
    if not isinstance(value, str):
        raise ValueError("worker outcome is not a string")
    if outcome == "error":
        return value
    decoded = json.loads(value)
    if outcome == "request":
        if not isinstance(decoded, dict) or not isinstance(decoded.get("body"), str):
            raise ValueError("worker request reply is not an HTTP request object")
        body = json.loads(decoded["body"])
        if not isinstance(body, dict):
            raise ValueError("worker request body is not an object")
        decoded = {**decoded, "body": body}
    return decoded


def _serialize_args(args: dict[str, Any]) -> bytes:
    """Serialize a request body once (#27, lone-surrogate and type checks)."""
    _reject_lone_surrogates(args)
    try:
        body = json.dumps(args, ensure_ascii=True, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BamlValidationError(f"BAML request is not serializable: {_sanitize_error(exc)}") from None
    data = body.encode("ascii")
    if len(data) > _REQUEST_CAP:
        raise BamlValidationError(f"BAML request body is {len(data)} bytes, over the {_REQUEST_CAP}-byte cap")
    return data


def _reject_lone_surrogates(value: Any) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise BamlValidationError("BAML request contains a lone surrogate") from None
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_lone_surrogates(key)
            _reject_lone_surrogates(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_lone_surrogates(item)


def _worker_call(op: str, args: dict[str, Any]) -> tuple[str, str]:
    """Run one fixed op on the worker; returns ``(outcome, value)``."""
    return _CLIENT.call(op, args)


def _reset_worker_for_tests(test_mode: bool = False, **config: Any) -> None:
    """Terminate and discard the worker, the source snapshot and the fault log."""
    global _CLIENT
    old = _CLIENT
    old.stop(graceful=False, timeout=_REAP_BOUND_S + 3.0)
    _enum_literal_map.cache_clear()
    _CLIENT = _Client(test_mode=test_mode, **config)


def _atexit_shutdown() -> None:
    client = _CLIENT
    if os.getpid() != client.owner_pid:
        return  # a fork child never touches inherited worker state
    client.stop(graceful=True, timeout=_EXIT_GRACE_S + 0.4)


_LOG = logging.getLogger(__name__)
_CLIENT = _Client()
atexit.register(_atexit_shutdown)
