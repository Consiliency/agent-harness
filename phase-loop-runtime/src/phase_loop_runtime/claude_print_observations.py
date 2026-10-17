"""Bounded, content-free observations of native Claude stream-json frames.

This reducer is diagnostic only. It cannot admit a result or supply review text.
Wire shapes follow anthropics/claude-agent-sdk-python at
f93e29cc951cd5fddcaaed9f3c49c3c38dedd6ab (types.py and message_parser.py).
No SDK dependency or transport is used.
"""
from __future__ import annotations

from hashlib import sha256
import json
import posixpath
import re
from typing import Callable


RESULT_SUBTYPES = frozenset({
    "success", "error_during_execution", "error_max_turns", "error_max_budget_usd",
    "error_max_structured_output_retries",
})
ERROR_CATEGORIES = frozenset({
    "auth", "usage_limit", "env_failure", "tool_denied", "timeout", "signal",
    "authentication_failed", "billing_error", "rate_limit", "invalid_request",
    "server_error", "unknown",
})
_MODEL = re.compile(r"claude-(?:opus|sonnet|haiku)-[0-9]{1,2}(?:-[0-9]{1,2})?(?:-[0-9]{8})?", re.ASCII)
_TOOL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}", re.ASCII)
MAX_EVENTS = 512
MAX_TOOLS = 64
MAX_MODELS = 4
MAX_ERRORS = 32
MAX_BLOCKS = 128
MAX_FINGERPRINT_BYTES = 65536
MAX_FINGERPRINT_DEPTH = 64
_SERVER_TOOLS = frozenset({
    "advisor", "web_search", "web_fetch", "code_execution", "bash_code_execution",
    "text_editor_code_execution", "tool_search_tool_regex", "tool_search_tool_bm25",
})


def _block_shape(block: object, role: str) -> bool:
    # Closed diagnostic compatibility subset of the pinned decoder. Extra block
    # fields and unsupported variants are unproven, never silently discarded.
    # Tool inputs remain opaque dictionaries; only Read.file_path is observed.
    if not isinstance(block, dict):
        return False
    kind = block.get("type")
    if kind == "text":
        return block.keys() == {"type", "text"} and isinstance(block["text"], str)
    if kind == "thinking" and role == "assistant":
        return (block.keys() == {"type", "thinking", "signature"}
                and isinstance(block["thinking"], str) and isinstance(block["signature"], str))
    if kind in ("tool_use", "server_tool_use") and role == "assistant":
        return (block.keys() == {"type", "id", "name", "input"}
                and _tool_key(block["id"]) is not None
                and isinstance(block["name"], str)
                and (kind == "tool_use" or block["name"] in _SERVER_TOOLS)
                and isinstance(block["input"], dict))
    if kind == "tool_result" and role == "user":
        if (not {"type", "tool_use_id"} <= block.keys()
                or block.keys() - {"type", "tool_use_id", "content", "is_error"}
                or _tool_key(block["tool_use_id"]) is None
                or type(block.get("is_error", False)) is not bool):
            return False
        content = block.get("content")
        # The pinned decoder leaves nested dicts opaque. Our supported nested
        # subset is text only, with no recursion; images/documents/new variants
        # need an explicit compatibility review before they can prove a Read.
        return (content is None or isinstance(content, str)
                or isinstance(content, list) and len(content) <= MAX_BLOCKS
                and all(isinstance(part, dict) and part.keys() == {"type", "text"}
                        and part.get("type") == "text" and isinstance(part["text"], str)
                        for part in content))
    return False


def _fingerprint_budget(value: object, budget: list[int], depth: int = 0) -> bool:
    # Bound encoder work/temporary allocations too: iterencode alone can allocate
    # one arbitrarily large escaped string or sorted dictionary-key list.
    if depth > MAX_FINGERPRINT_DEPTH:
        return False
    budget[0] -= 1 + (len(value) if isinstance(value, (str, list, dict)) else 0)
    if budget[0] < 0:
        return False
    if isinstance(value, dict):
        return all(isinstance(key, str) and _fingerprint_budget(key, budget, depth + 1)
                   and _fingerprint_budget(item, budget, depth + 1)
                   for key, item in value.items())
    if isinstance(value, list):
        return all(_fingerprint_budget(item, budget, depth + 1) for item in value)
    if type(value) is int:
        return value.bit_length() <= MAX_FINGERPRINT_BYTES
    return value is None or isinstance(value, (str, int, float, bool))


def _frame_fingerprint(kind: str, model: object, content: object) -> bytes | None:
    # Semantic replay identity excludes UUIDs, message IDs and other envelope
    # metadata. Native split assistant blocks may share an ID: distinct content
    # is accepted; repeated same-role/model content is conservatively ambiguous.
    # No frame, content, or fingerprint is exported or kept by reference.
    if not _fingerprint_budget([kind, model, content], [MAX_FINGERPRINT_BYTES]):
        return None
    digest = sha256()
    remaining = MAX_FINGERPRINT_BYTES
    try:
        for chunk in json.JSONEncoder(sort_keys=True, ensure_ascii=True, allow_nan=False).iterencode(
                (kind, model, content)):
            if len(chunk) > remaining:
                return None
            remaining -= len(chunk)
            digest.update(chunk.encode("ascii"))
    except (ValueError, TypeError, RecursionError):
        return None
    return digest.digest()


def _model(value: object) -> str | None:
    return value if isinstance(value, str) and len(value) <= 80 and _MODEL.fullmatch(value) else None


def _tool_key(value: object) -> str | None:
    if isinstance(value, str) and _TOOL_ID.fullmatch(value):
        return sha256(value.encode()).hexdigest()
    return None


def _path_digest(value: object) -> str | None:
    # Hash only canonical absolute paths inside the staged tree. Do not resolve a
    # host path, retain a filename, or mistake a substring in tool output for a read.
    if (isinstance(value, str) and len(value) <= 4096
            and value.startswith("/seat/tree/") and posixpath.normpath(value) == value
            and all(32 <= ord(char) < 127 for char in value)):
        return sha256(value.encode()).hexdigest()
    return None


class ClaudePrintObservations:
    """Keep only closed labels, validated model names, counters and digests.

    Unknown, foreign, malformed, duplicate or excess relevant frames invalidate
    positive observation claims, without changing the print admission reducer.
    Native subagent frames cannot prove a top-level requested-model/file read.
    """

    def __init__(self, session: str | None, requested_model: str | None,
                 classify_error: Callable[[str], str]) -> None:
        self._session = session
        self._classify_error = classify_error
        self.requested_model = _model(requested_model)
        self.events = 0
        self.invalid = False
        self.truncated = False
        self.rejected_session_count = 0
        self.result_subtype: str | None = None
        self.result_is_error: bool | None = None
        self.error_count = 0
        self.error_categories: set[str] = set()
        self.models: dict[str, set[str]] = {"init": set(), "assistant": set()}
        self.model_unknown = False
        self.tools: dict[str, dict[str, object]] = {}
        self._uuids: set[str] = set()
        self._fingerprints: set[bytes] = set()
        self._init_seen = False
        self._result_seen = False

    def malformed(self) -> None:
        self.invalid = True

    def _error(self, value: object, *, closed: bool = False) -> None:
        if self.error_count >= MAX_ERRORS:
            self.truncated = self.invalid = True
            return
        self.error_count += 1
        category = ((value if closed else self._classify_error(value))
                    if isinstance(value, str) and len(value) <= 4096 else "unknown")
        self.error_categories.add(category if category in ERROR_CATEGORIES else "unknown")

    def _observe_model(self, source: str, value: object) -> None:
        model = _model(value)
        if model is None:
            self.model_unknown = True
        elif len(self.models[source]) < MAX_MODELS or model in self.models[source]:
            self.models[source].add(model)
        else:
            self.truncated = self.invalid = True

    def event(self, event: dict[str, object]) -> None:
        kind, subtype = event.get("type"), event.get("subtype")
        if kind not in ("assistant", "user", "result", "system"):
            return
        if kind == "system" and subtype not in ("init", "api_retry"):
            return
        if self.events >= MAX_EVENTS:
            self.truncated = self.invalid = True
            return
        self.events += 1
        if self._session is None or event.get("session_id") != self._session:
            self.rejected_session_count += 1
            self.invalid = True
            return
        if event.get("parent_tool_use_id") is not None:
            self.invalid = True
            return
        # UUID is optional on older frames. Content replay checks below apply
        # even without it, or when it changes on an otherwise repeated frame.
        if "uuid" in event:
            key = _tool_key(event["uuid"])
            if key is None or key in self._uuids:
                self.invalid = True
                return
            self._uuids.add(key)
        if kind == "system" and subtype == "init":
            if self._init_seen or self._result_seen:
                self.invalid = True
                return
            self._init_seen = True
            self._observe_model("init", event.get("model"))
            return
        if not self._init_seen or self._result_seen:
            self.invalid = True
            return
        if kind == "result":
            self._result_seen = True
            self.result_subtype = subtype if isinstance(subtype, str) and subtype in RESULT_SUBTYPES else "unknown"
            flag = event.get("is_error")
            self.result_is_error = flag if type(flag) is bool else None
            if self.result_is_error is None:
                self.invalid = True
            errors = event.get("errors", [])
            if not isinstance(errors, list):
                self.invalid = True
                self._error(None)
            else:
                for error in errors[:MAX_ERRORS]:
                    if not isinstance(error, str):
                        self.invalid = True
                    self._error(error)
                if len(errors) > MAX_ERRORS:
                    self.truncated = self.invalid = True
            if event.get("is_error") is True and not errors:
                self._error(None)
            return
        if kind == "system":
            if not isinstance(event.get("error"), str):
                self.invalid = True
            self._error(event.get("error"), closed=True)
            return
        message = event.get("message")
        if not isinstance(message, dict):
            self.invalid = True
            return
        if message.get("role") != kind:
            self.invalid = True
            return
        if kind == "assistant":
            self._observe_model("assistant", message.get("model"))
            if event.get("error") is not None:
                if not isinstance(event["error"], str):
                    self.invalid = True
                self._error(event["error"], closed=True)
        content = message.get("content")
        fingerprint = _frame_fingerprint(kind, message.get("model") if kind == "assistant" else None, content)
        if fingerprint is None:
            self.truncated = self.invalid = True
            return
        if fingerprint in self._fingerprints:
            self.invalid = True
            return
        self._fingerprints.add(fingerprint)
        if kind == "user" and isinstance(content, str):
            return  # Ordinary input is not tool evidence.
        if not isinstance(content, list):
            self.invalid = True
            return
        if len(content) > MAX_BLOCKS:
            self.truncated = self.invalid = True
            return
        for block in content:
            if not _block_shape(block, kind):
                self.invalid = True
                continue
            block_kind = block.get("type")
            if block_kind == "tool_use" and kind == "assistant":
                key = _tool_key(block.get("id"))
                if key is None or key in self.tools:
                    self.invalid = True
                    continue
                if len(self.tools) >= MAX_TOOLS:
                    self.truncated = self.invalid = True
                    continue
                name = "Read" if block.get("name") == "Read" else "other"
                inputs = block.get("input")
                if not isinstance(inputs, dict) or not isinstance(block.get("name"), str):
                    self.invalid = True
                path = _path_digest(inputs.get("file_path")) if isinstance(inputs, dict) and name == "Read" else None
                self.tools[key] = {"name": name, "path_sha256": path, "result": "pending"}
            elif block_kind == "tool_result" and kind == "user":
                key = _tool_key(block.get("tool_use_id"))
                tool = self.tools.get(key) if key is not None else None
                if tool is None or tool["result"] != "pending":
                    self.invalid = True
                    continue
                error = block.get("is_error", False)
                tool["result"] = "success" if error is False else "error" if error is True else "unknown"
                if error is not False and error is not True:
                    self.invalid = True
            elif block_kind in ("tool_use", "tool_result"):
                self.invalid = True

    def snapshot(self) -> dict[str, object]:
        init, assistant = self.models["init"], self.models["assistant"]
        if self.invalid:
            status = "unproven"
        elif self.model_unknown or self.requested_model is None:
            status = "unknown"
        elif len(init | assistant) > 1:
            status = "contradictory"
        elif (init | assistant) - {self.requested_model}:
            status = "mismatch"
        elif not init or not assistant:
            status = "missing"
        else:
            status = "match"
        return {
            "schema": "claude-print-observations.v1",
            "valid": not self.invalid, "truncated": self.truncated,
            "event_count": self.events, "rejected_session_count": self.rejected_session_count,
            "result_subtype": self.result_subtype,
            "result_is_error": self.result_is_error,
            "error_count": self.error_count, "error_categories": sorted(self.error_categories),
            "requested_model": self.requested_model or "unknown",
            "init_models": sorted(init), "assistant_models": sorted(assistant),
            "model_status": status,
            "tools": [{"tool_use_id_sha256": key, **tool,
                       "read_completed": (status == "match" and tool["name"] == "Read"
                                          and tool["path_sha256"] is not None and tool["result"] == "success")}
                      for key, tool in self.tools.items()],
        }
