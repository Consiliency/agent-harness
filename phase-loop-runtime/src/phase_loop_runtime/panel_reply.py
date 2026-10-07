"""A strict, machine-consumable reply for advisor-board seats, and the verifier for it.

A seat's reply is verified only if it parses as ONE JSON object that matches `PanelSeatReply`
exactly (types, no extra fields, no coercion) and carries the data its mode requires. The
verifier is deliberately not BAML's parser: BAML v1's `.parse` is lenient by design, and a
spike against 0.20.1 showed it accepting replies that must be rejected -- a truncated reply
became `AGREE` with its findings dropped, `summary: 5` became `"5"`, `findings: "none"` became
an empty list, and with two JSON objects it silently took the first. Those are the failures a
verifier exists to catch, so the extraction and the validation here are strict and typed.

`extract_reply` never raises on seat content: it returns either the typed reply or a typed
failure kind, so a caller can map it to a leg status and fail closed. Nothing here launches a
seat, reads a file, or touches the BAML worker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

#: Reply modes. `review` is the pre-merge gate (a verdict is required); `advisory` is analysis
#: (no verdict). They mirror `panel_invoker.PANEL_MODES`.
MODES = ("review", "advisory")

Severity = Literal["blocking", "non_blocking"]
Verdict = Literal["AGREE", "PARTIALLY AGREE", "DISAGREE"]

_MAX_FINDINGS = 200
_MAX_TITLE = 300
_MAX_BODY = 20_000
_MAX_SUMMARY = 20_000
_MAX_LOCATION = 500
_MAX_REPLY_BYTES = 1_000_000

#: Typed failure kinds. A caller maps each to a non-usable leg status; none is a verdict.
FAILURE_KINDS = (
    "empty",                # no text
    "too_large",            # over the size cap
    "no_json",              # no complete JSON object (a truncated reply lands here)
    "ambiguous_reply",      # more than one JSON object that could be the reply
    "schema_mismatch",      # wrong shape, wrong type, a missing or an extra field
    "verdict_missing",      # review mode, no verdict
    "verdict_forbidden",    # advisory mode, a verdict present
    "verdict_inconsistent", # the verdict contradicts the findings
    "invalid_mode",         # the caller named an unknown mode
)


class PanelFinding(BaseModel):
    """One finding. Strict: no extra fields, no type coercion."""

    model_config = ConfigDict(extra="forbid", strict=True)

    severity: Severity
    title: str = Field(min_length=1, max_length=_MAX_TITLE)
    body: str = Field(min_length=1, max_length=_MAX_BODY)
    location: str | None = Field(default=None, min_length=1, max_length=_MAX_LOCATION)

    @model_validator(mode="after")
    def _non_blank(self) -> "PanelFinding":
        if not self.title.strip() or not self.body.strip():
            raise ValueError("a finding needs a non-blank title and body")
        return self


class PanelSeatReply(BaseModel):
    """The whole reply. `verdict` is required in review mode and forbidden in advisory mode."""

    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Verdict | None = None
    summary: str = Field(min_length=1, max_length=_MAX_SUMMARY)
    findings: list[PanelFinding] = Field(max_length=_MAX_FINDINGS)

    @model_validator(mode="after")
    def _non_blank(self) -> "PanelSeatReply":
        if not self.summary.strip():
            raise ValueError("the summary must not be blank")
        return self


@dataclass(frozen=True)
class ReplyOutcome:
    """Exactly one of `reply` and `failure` is set."""

    reply: PanelSeatReply | None = None
    failure: str | None = None
    detail: str | None = None       # a short, content-free reason (field names, never reply text)
    wrapped: bool = False           # the JSON object sat inside surrounding text

    @property
    def verified(self) -> bool:
        return self.reply is not None


def _fail(kind: str, detail: str | None = None) -> ReplyOutcome:
    assert kind in FAILURE_KINDS
    return ReplyOutcome(failure=kind, detail=detail)


def _objects(text: str) -> tuple[list[tuple[int, int, Any]], bool]:
    """Every top-level JSON object in ``text`` as ``(start, end, value)``, found by decoding from
    each `{` that is not already inside a decoded object, and whether the FIRST `{` in the text
    decoded to a complete object. Strings and escapes are the decoder's business, so a brace
    inside a string is never mistaken for structure."""
    decoder = json.JSONDecoder()
    found: list[tuple[int, int, Any]] = []
    first_decoded: bool | None = None
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return found, bool(first_decoded)
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            if first_decoded is None:
                first_decoded = False
            index = start + 1       # not a complete object here (e.g. a truncated one)
            continue
        if first_decoded is None:
            first_decoded = True
        if isinstance(value, dict):
            found.append((start, end, value))
        index = end


def _shape_detail(error: ValidationError) -> str:
    fields = sorted({".".join(str(part) for part in item["loc"]) or "<root>" for item in error.errors()})
    return "fields: " + ", ".join(fields[:8])


def extract_reply(text: str | None, mode: str) -> ReplyOutcome:
    """Verify a seat's reply text. Never raises on seat content."""
    if mode not in MODES:
        return _fail("invalid_mode")
    text = text or ""
    if not text.strip():
        return _fail("empty")
    if len(text.encode("utf-8", errors="replace")) > _MAX_REPLY_BYTES:
        return _fail("too_large")
    objects, first_decoded = _objects(text)
    if not objects:
        return _fail("no_json")

    # Several objects: the reply is whichever one(s) match the schema; if more than one does, the
    # reply is ambiguous and nothing is verified (never "the first" or "the last").
    candidates: list[tuple[PanelSeatReply, bool]] = []
    first_error: ValidationError | None = None
    for start, end, value in objects:
        try:
            reply = PanelSeatReply.model_validate(value)
        except ValidationError as exc:
            first_error = first_error or exc
            continue
        candidates.append((reply, text[:start].strip() != "" or text[end:].strip() != ""))
    if not candidates:
        if not first_decoded:
            # The text opens an object that never completes: a truncated reply, whose inner
            # (complete) objects are fragments of it, not replies.
            return _fail("no_json")
        return _fail("schema_mismatch", _shape_detail(first_error) if first_error else None)
    if len(candidates) > 1:
        return _fail("ambiguous_reply", f"{len(candidates)} replies")
    reply, wrapped = candidates[0]

    if mode == "advisory":
        if reply.verdict is not None:
            return _fail("verdict_forbidden")
        return ReplyOutcome(reply=reply, wrapped=wrapped)
    if reply.verdict is None:
        return _fail("verdict_missing")
    blocking = sum(1 for finding in reply.findings if finding.severity == "blocking")
    if reply.verdict == "DISAGREE" and blocking == 0:
        return _fail("verdict_inconsistent", "DISAGREE without a blocking finding")
    if reply.verdict == "AGREE" and blocking:
        return _fail("verdict_inconsistent", "AGREE with a blocking finding")
    if reply.verdict == "PARTIALLY AGREE" and not reply.findings:
        return _fail("verdict_inconsistent", "PARTIALLY AGREE without a finding")
    return ReplyOutcome(reply=reply, wrapped=wrapped)


def derive_terminal_verdict(reply: PanelSeatReply | None) -> str | None:
    """The reply's verdict in the vocabulary `panel_invoker.terminal_verdict` uses, or None."""
    return reply.verdict if reply is not None else None


def render_reply_instructions(mode: str) -> str:
    """The instructions to append to a seat's prompt when structured replies are requested.

    Generated from the same model that verifies the reply, so the schema the seat is shown can
    never drift from the schema it is checked against."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    schema = PanelSeatReply.model_json_schema()
    properties = schema["properties"]
    if mode == "advisory":
        properties = {name: value for name, value in properties.items() if name != "verdict"}
    shown = {"type": "object", "additionalProperties": False, "properties": properties,
             "required": ["summary", "findings"] if mode == "advisory" else ["verdict", "summary", "findings"],
             "$defs": schema.get("$defs", {})}
    rules = [
        "Reply with exactly ONE JSON object and nothing else: no prose before or after it, "
        "no second JSON object, no code fence is needed.",
        "Use only the fields in the schema. Every string is plain text; `findings` is a list "
        "(use [] when there are none); a finding's severity is `blocking` or `non_blocking`.",
    ]
    if mode == "review":
        rules += [
            "`verdict` is exactly one of AGREE, PARTIALLY AGREE, DISAGREE.",
            "DISAGREE requires at least one `blocking` finding; AGREE allows none; "
            "PARTIALLY AGREE requires at least one finding.",
        ]
    else:
        rules.append("Do NOT include a `verdict` field: this is advice, not a verdict.")
    return (
        "## Reply format\n\n"
        + "\n".join(f"- {rule}" for rule in rules)
        + "\n\nJSON Schema of the reply:\n\n```json\n"
        + json.dumps(shown, indent=2, sort_keys=True)
        + "\n```\n"
    )
