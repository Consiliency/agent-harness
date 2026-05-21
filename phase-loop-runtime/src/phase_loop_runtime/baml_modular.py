from __future__ import annotations

import json
import os
import re
import site
import sysconfig
import types
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .models import BLOCKER_CLASSES, PHASE_STATUSES


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

    @field_validator("terminal_status")
    @classmethod
    def _terminal_status_literal(cls, value: str) -> str:
        if value not in PHASE_STATUSES:
            raise ValueError(f"invalid terminal_status: {value}")
        return value

    @field_validator("blocker_class")
    @classmethod
    def _blocker_class_literal(cls, value: str | None) -> str | None:
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
    value: PhaseLoopCloseoutV1


def build_baml_request(function_name: str, payload: dict[str, Any] | None = None) -> BamlRequest:
    runtime, ctx_manager = _runtime()
    try:
        request = runtime.build_request_sync(
            function_name,
            payload or {},
            ctx_manager.clone_context(),
            None,
            None,
            _filtered_env(),
            False,
        )
    except Exception as exc:  # pragma: no cover - exact BAML errors vary by version
        raise BamlValidationError(_sanitize_error(exc)) from exc
    body = request.body.json()
    return BamlRequest(
        id=getattr(request, "id", None),
        url=str(request.url),
        method=str(request.method),
        headers={str(key): str(value) for key, value in dict(request.headers).items()},
        body=body,
        prompt=_extract_prompt(body),
    )


def parse_baml_response(function_name: str, raw_text: str) -> ParsedResponse:
    runtime, ctx_manager = _runtime()
    enum_module, class_module = _type_modules()
    try:
        value = runtime.parse_llm_response(
            function_name,
            str(raw_text or ""),
            enum_module,
            class_module,
            class_module,
            False,
            ctx_manager.clone_context(),
            None,
            None,
            _filtered_env(),
        )
        if isinstance(value, PhaseLoopCloseoutV1):
            typed = value
        elif hasattr(value, "model_dump"):
            typed = PhaseLoopCloseoutV1.model_validate(value.model_dump())
        elif isinstance(value, dict):
            typed = PhaseLoopCloseoutV1.model_validate(value)
        else:
            typed = PhaseLoopCloseoutV1.model_validate(_find_json_payload(str(raw_text or "")))
    except Exception as exc:
        raise BamlValidationError(_sanitize_error(exc)) from exc
    return ParsedResponse(function_name=function_name, payload=typed.model_dump(), value=typed)


@lru_cache(maxsize=1)
def _runtime():
    from baml_py import BamlCtxManager, BamlRuntime

    files = _read_baml_files()
    runtime = BamlRuntime.from_files("baml_src", files, _filtered_env())
    return runtime, BamlCtxManager(runtime)


def _read_baml_files() -> dict[str, str]:
    src_dir = _baml_src_dir()
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(src_dir.glob("*.baml"))
        if path.is_file()
    }


def _baml_src_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "baml_src",
        Path(sysconfig.get_paths().get("data", "")) / "share" / "phase-loop-runtime" / "baml_src",
        Path(site.USER_BASE) / "share" / "phase-loop-runtime" / "baml_src",
    ]
    for candidate in candidates:
        if (candidate / "emit_phase_closeout.baml").exists():
            return candidate
    raise BamlValidationError("BAML source file not found: emit_phase_closeout.baml")


@lru_cache(maxsize=1)
def _type_modules() -> tuple[types.ModuleType, types.ModuleType]:
    enum_module = types.ModuleType("phase_loop_runtime.baml_enums")
    class_module = types.ModuleType("phase_loop_runtime.baml_classes")
    class_module.PhaseLoopCloseoutV1 = PhaseLoopCloseoutV1
    return enum_module, class_module


def _filtered_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if value is not None}


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
    message = re.sub(r"(?i)(api[_-]?key|authorization|token|secret|password)[^\\s,;]*", r"\\1=<redacted>", message)
    message = " ".join(message.split())
    if len(message) > 500:
        message = message[:497] + "..."
    return message or exc.__class__.__name__
