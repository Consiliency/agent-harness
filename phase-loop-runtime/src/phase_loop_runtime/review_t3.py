"""Versioned, bounded T3 HOST_ATTESTED relay. All tool calls are returned data.

The driving host asserts original terminal identity; T3 exposes no terminal-item
flag. This observed profile is not a schema guarantee or authentication. Shared
checkout dispatch is supported; generated worktree locations cannot be bound in
advance by this profile and therefore refuse. No durable redispatch guarantee is
inferred from clientRequestId. Reading terminal results acknowledges delivery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
import hashlib
import json
from pathlib import Path
from typing import Any

from .review_contract import MAX_BYTES, ReviewRefused, canonical_json

PROFILE_VERSION = "t3_host_attested.v1"
OBSERVATION_VERSION = "t3_tool_observation.v1"
REGISTRATION_VERSION = "t3_registration.v1"
TERMINAL_VERSION = "t3_original_terminal.v1"
INTAKE_VERSION = "t3_intake.v1"
REQUIRED_FEATURES = ("appOwnedSubagents", "asyncPolling", "threadManagement", "incrementalThreadRead")
IDENTITY_KEYS = ("taskId", "childThreadId", "childRunId")
MAX_RECOVERY_BYTES = 2 * MAX_BYTES
MAX_OBSERVATION_BYTES = 8 * MAX_BYTES
MAX_RETAINED_BYTES = 24 * MAX_BYTES
MAX_CAPABILITY_BYTES = MAX_BYTES
MAX_PROMPT_BYTES = 8 * MAX_BYTES
MAX_METADATA_BYTES = 32_768
MAX_TIMELINE_PAGES = 128
MAX_TEXT_PAGES = 256
MAX_ITEMS = 4096
MAX_ID_CHARS = 2048
REDISPATCH_CAPABLE = False
_ITEM_IDENTITY = ("itemId", "position", "sourceThreadId", "runId", "visibility", "type",
                  "createdBy", "creationSource", "status", "updatedAt", "messageId", "title", "subagentId")


def require(ok: bool, code: str = "binding_mismatch") -> None:
    if not ok:
        raise ReviewRefused(code)


def closed_observation_errors(function):
    """Malformed host JSON exposes only a closed code, never model strings."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ReviewRefused:
            raise
        except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
            raise ReviewRefused("result_unavailable") from None
    return wrapped


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def text_id(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_ID_CHARS


def relay_json(value: Any) -> bytes:
    """JSON escapes retain surrogate code units until complete item reassembly."""
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        raise ReviewRefused("result_unavailable") from None


def host_scope(value: Any) -> dict:
    require(type(value) is dict and set(value) == {"parent_thread_id", "checkout"})
    require(all(text_id(v) for v in value.values()))
    try:
        checkout = Path(value["checkout"])
        require(checkout.is_absolute() and checkout.is_dir())
        return {"parent_thread_id": value["parent_thread_id"], "checkout": str(checkout.resolve(strict=True))}
    except (OSError, RuntimeError, ValueError):
        raise ReviewRefused("binding_mismatch") from None


def validate_charter(value: Any) -> dict:
    require(type(value) is dict and set(value) <= {"schema", "review_brief", "host_scope", "allow_correction"})
    require(value.get("schema") == "t3_host_charter.v1" and type(value.get("review_brief")) is str)
    require(bool(value["review_brief"].strip()) and type(value.get("allow_correction", False)) is bool)
    result = {**value, "host_scope": host_scope(value.get("host_scope")),
              "allow_correction": value.get("allow_correction", False)}
    require(len(canonical_json(result)) <= MAX_BYTES, "limit_exceeded")
    return result


@dataclass(frozen=True)
class HostAction:
    """Private arguments; metadata() never exposes prompt or raw tool identity."""

    kind: str
    request_binding: str
    tool: str | None = None
    arguments: dict = field(default_factory=dict, repr=False)
    payload_digest: str | None = None

    def metadata(self) -> dict:
        return {"schema": "t3_host_action.v1", "kind": self.kind,
                "request_binding": self.request_binding, "tool": self.tool,
                "payload_digest": self.payload_digest, "profile": PROFILE_VERSION,
                "recovery_byte_ceiling": MAX_RECOVERY_BYTES, "redispatch_capable": REDISPATCH_CAPABLE}

    def private_payload(self) -> dict:
        return {**self.metadata(), "arguments": self.arguments}


def runtime_mode(capabilities: dict) -> str:
    """Observed host posture only; the inherited child's permissions are not attested."""
    require(type(capabilities) is dict and capabilities.get("runtimeMode") in
            ("approval-required", "auto-accept-edits", "auto", "full-access"), "result_unavailable")
    return capabilities["runtimeMode"]


@closed_observation_errors
def dispatch_payload(binding: str, prompt: str, target: dict, capabilities: dict) -> dict:
    """Only arguments present in the inspected live T3 schema are emitted."""
    require(type(capabilities) is dict and len(relay_json(capabilities)) <= MAX_CAPABILITY_BYTES,
            "result_unavailable")
    features = capabilities.get("features", {})
    require(type(features) is dict and all(features.get(k) is True for k in REQUIRED_FEATURES), "result_unavailable")
    require(capabilities.get("interactionMode") == "default", "result_unavailable")
    runtime_mode(capabilities)
    require(type(target) is dict and set(target) <= {"providerInstanceId", "model", "options"})
    require(text_id(target.get("providerInstanceId")) and text_id(target.get("model")))
    providers = capabilities.get("providers")
    require(type(providers) is list, "result_unavailable")
    matches = [p for p in providers if type(p) is dict and p.get("providerInstanceId") == target["providerInstanceId"]]
    require(len(matches) == 1, "result_unavailable")
    provider = matches[0]
    require(provider.get("canRunChildTask") is True and provider.get("constraints") == [], "result_unavailable")
    if capabilities.get("inheritedProviderInstanceId") != target["providerInstanceId"]:
        require(provider.get("canRunCrossProviderChildTask") is True, "result_unavailable")
    models = provider.get("models")
    require(type(models) is list, "result_unavailable")
    models = [m for m in models if type(m) is dict and m.get("id") == target["model"]]
    require(len(models) == 1, "result_unavailable")
    options = target.get("options", {})
    require(type(options) is dict)
    declared = models[0].get("options")
    if declared is None:  # Optional/null in the exposed model schema.
        declared = []
    require(type(declared) is list, "result_unavailable")
    # Omitting a declared option inherits mutable host settings. This profile
    # requires explicit choices so a correction preserves the requested options.
    require(all(type(o) is dict and text_id(o.get("id")) for o in declared) and
            len({o["id"] for o in declared}) == len(declared) and
            set(options) == {o["id"] for o in declared}, "result_unavailable")
    for name, value in options.items():
        declarations = [o for o in declared if o.get("id") == name]
        require(len(declarations) == 1, "result_unavailable")
        opt = declarations[0]
        if opt.get("type") == "select":
            choices = opt.get("options")
            require(type(choices) is list and all(type(v) is dict and text_id(v.get("id")) for v in choices),
                    "result_unavailable")
            require(len({v["id"] for v in choices}) == len(choices), "result_unavailable")
        require((opt.get("type") == "boolean" and type(value) is bool) or
                (opt.get("type") == "select" and type(value) is str and
                 value in [v["id"] for v in choices]), "result_unavailable")
    require(type(prompt) is str and len(prompt.encode("utf-8")) <= MAX_PROMPT_BYTES, "result_unavailable")
    return {"task": prompt, "target": json.loads(canonical_json(target)), "mode": "async",
            "role": "review", "isolation": "shared", "interactionMode": "default",
            "clientRequestId": "typed-review-v1-" + binding}


def observation(value: Any, tool: str) -> tuple[dict, dict]:
    require(type(value) is dict and set(value) == {"schema", "tool", "arguments", "result"}, "result_unavailable")
    require(value["schema"] == OBSERVATION_VERSION and value["tool"] == tool, "result_unavailable")
    require(type(value["arguments"]) is dict and type(value["result"]) is dict, "result_unavailable")
    require(len(relay_json(value)) <= MAX_OBSERVATION_BYTES, "result_unavailable")
    return value["arguments"], value["result"]


def registered_identity(result: dict, target: dict) -> dict:
    require(all(text_id(result.get(k)) for k in IDENTITY_KEYS))
    require(result.get("providerInstanceId") == target["providerInstanceId"] and result.get("model") == target["model"])
    return {k: result[k] for k in (*IDENTITY_KEYS, "providerInstanceId", "model")}


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def _read(value, identity, scope, *, item_id=None, offset=None, cursor=None):
    args, page = observation(value, "t3_thread_read")
    require(set(args) <= {"threadId", "view", "afterPosition", "itemId", "textOffset", "limit", "maxCharsPerItem", "runLimit"}, "result_unavailable")
    require(args.get("threadId") == identity["childThreadId"] and args.get("view") == "messages", "result_unavailable")
    for name in ("limit", "maxCharsPerItem", "runLimit"):
        require(args.get(name) is None or type(args[name]) is int and args[name] > 0, "result_unavailable")
    require(args.get("itemId") == item_id and args.get("textOffset") == offset and args.get("afterPosition") == cursor,
            "result_unavailable")
    thread = page.get("thread")
    require(type(thread) is dict and thread.get("threadId") == identity["childThreadId"] and
            thread.get("parentThreadId") == scope["parent_thread_id"] and thread.get("relationshipToParent") == "subagent",
            "result_unavailable")
    try:
        require(type(thread.get("worktreePath")) is str and Path(thread["worktreePath"]).resolve(strict=True) == Path(scope["checkout"]), "result_unavailable")
    except (OSError, RuntimeError, ValueError):
        raise ReviewRefused("result_unavailable") from None
    require(type(page.get("items")) is list and type(page.get("recentRuns")) is list, "result_unavailable")
    for run in page["recentRuns"]:
        require(type(run) is dict, "result_unavailable")
        if run.get("runId") == identity["childRunId"]:
            require(run.get("status") == "completed" and run.get("model") == identity["model"] and
                    run.get("providerInstanceId") == identity["providerInstanceId"], "result_unavailable")
    return page


def _stable(item):
    require(type(item) is dict and all(k in item for k in _ITEM_IDENTITY if k != "subagentId"), "result_unavailable")
    return {k: item.get(k) for k in _ITEM_IDENTITY}


def _chunk(item, offset):
    require(type(item.get("text")) is str and type(item.get("textTruncated")) is bool and "nextTextOffset" in item,
            "result_unavailable")
    text = item["text"]
    next_offset = item["nextTextOffset"]
    if item["textTruncated"]:
        require(type(next_offset) is int and next_offset > offset and next_offset == offset + utf16_length(text), "result_unavailable")
    else:
        require(next_offset is None, "result_unavailable")
    return text, next_offset


@dataclass(frozen=True)
class RecoveredDelivery:
    body: bytes = field(repr=False)
    envelope: bytes = field(repr=False)
    observations: bytes = field(repr=False)
    evidence_digests: dict = field(repr=False)


@closed_observation_errors
def recover(binding: str, identity: dict, scope: dict, package: dict) -> RecoveredDelivery:
    """Full traversal plus attestation, then one item's exact UTF-16 text only."""
    require(type(package) is dict and set(package) == {"schema", "terminal", "completion", "timeline", "text", "evidence_digests"}, "result_unavailable")
    require(package["schema"] == INTAKE_VERSION, "result_unavailable")
    retained = relay_json(package)
    require(len(retained) <= MAX_RETAINED_BYTES, "result_unavailable")
    args, completion = observation(package["completion"], "task_status")
    require(args == {"taskId": identity["taskId"]}, "result_unavailable")
    require(all(completion.get(k) == v for k, v in identity.items()), "result_unavailable")
    require(completion.get("status") == "completed" and completion.get("workState") == "result_available", "result_unavailable")
    terminal = package["terminal"]
    require(type(terminal) is dict and set(terminal) == {"schema", "profile", "request_binding", "host_scope", *IDENTITY_KEYS, "itemId", "position", "updatedAt"}, "result_unavailable")
    require(terminal["schema"] == TERMINAL_VERSION and terminal["profile"] == PROFILE_VERSION and
            terminal["request_binding"] == binding and terminal["host_scope"] == scope and
            all(terminal[k] == identity[k] for k in IDENTITY_KEYS), "result_unavailable")
    timeline, chunks = package["timeline"], package["text"]
    require(type(timeline) is list and 0 < len(timeline) <= MAX_TIMELINE_PAGES and
            type(chunks) is list and len(chunks) <= MAX_TEXT_PAGES, "result_unavailable")
    cursor, maximum, seen, selected, last_original = None, -1, set(), None, None
    for index, wrapper in enumerate(timeline):
        page = _read(wrapper, identity, scope, cursor=cursor)
        require(bool(page["items"]) and type(page.get("hasMore")) is bool and "nextPosition" in page, "result_unavailable")
        for item in page["items"]:
            require(type(item) is dict and text_id(item.get("itemId")) and type(item.get("position")) is int, "result_unavailable")
            require(item["position"] > maximum and (cursor is None or item["position"] > cursor) and
                    item["itemId"] not in seen, "result_unavailable")
            seen.add(item["itemId"])
            require(len(seen) <= MAX_ITEMS, "result_unavailable")
            maximum = item["position"]
            if (item.get("runId") == identity["childRunId"] and item.get("sourceThreadId") == identity["childThreadId"]
                    and item.get("visibility") == "local" and item.get("creationSource") == "provider"
                    and item.get("createdBy") == "agent" and item.get("type") == "assistant_message"):
                last_original = item["itemId"]
            if item["itemId"] == terminal["itemId"]:
                selected = item
        next_cursor = page["nextPosition"]
        if page["hasMore"]:
            require(index < len(timeline) - 1 and type(next_cursor) is int and next_cursor >= maximum and
                    (cursor is None or next_cursor > cursor), "result_unavailable")
        else:
            require(index == len(timeline) - 1 and (next_cursor is None or type(next_cursor) is int and next_cursor == maximum), "result_unavailable")
        cursor = next_cursor
    require(timeline[-1]["result"]["hasMore"] is False and selected is not None and last_original == terminal["itemId"], "result_unavailable")
    require(selected["status"] == "completed" and selected["position"] == terminal["position"] and
            type(terminal["position"]) is int and selected["updatedAt"] == terminal["updatedAt"], "result_unavailable")
    stable = _stable(selected)
    require(len(canonical_json(stable)) <= MAX_METADATA_BYTES, "result_unavailable")
    text, offset = _chunk(selected, 0)
    pieces = [text.encode("utf-16-le", "surrogatepass")]
    units_bytes = len(pieces[0])
    require(units_bytes <= 2 * MAX_RECOVERY_BYTES, "result_unavailable")
    previous = text
    for wrapper in chunks:
        require(offset is not None, "result_unavailable")
        page = _read(wrapper, identity, scope, item_id=selected["itemId"], offset=offset)
        require(len(page["items"]) == 1, "result_unavailable")
        item = page["items"][0]
        require(_stable(item) == stable, "result_unavailable")
        text, offset = _chunk(item, offset)
        require(bool(text) and not previous.endswith("\ufffd") and not text.startswith("\ufffd"), "result_unavailable")
        part = text.encode("utf-16-le", "surrogatepass")
        units_bytes += len(part)
        require(units_bytes <= 2 * MAX_RECOVERY_BYTES, "result_unavailable")
        pieces.append(part)
        previous = text
    require(offset is None, "result_unavailable")
    try:
        body = b"".join(pieces).decode("utf-16-le", "strict").encode("utf-8", "strict")
    except UnicodeError:
        raise ReviewRefused("result_unavailable") from None
    require(len(body) <= MAX_RECOVERY_BYTES, "result_unavailable")
    # The status summary is deliberately unused: it has no completeness flag.
    metadata = {"schema": "t3_host_envelope.v1", "profile": PROFILE_VERSION, "provenance": "HOST_ATTESTED",
                "request_binding": binding, "identity": identity, "host_scope": scope,
                "terminal": stable, "completion": {"status": "completed", "workState": "result_available"}}
    require(len(canonical_json(metadata)) <= MAX_METADATA_BYTES, "result_unavailable")
    envelope = canonical_json({**metadata, "body": body.decode("utf-8")})
    require(len(envelope) <= 6 * len(body) + 65_536, "result_unavailable")
    return RecoveredDelivery(body, envelope, retained, package["evidence_digests"])
