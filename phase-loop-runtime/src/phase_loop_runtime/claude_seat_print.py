"""The jailed ``print`` transport (SEATS CLAUDE lane B; the print-route record's §4a items 4
and 5, agent-harness#1775).

``print`` is the jailed TUI command (``panel_invoker._broker_claude_tui_command`` with the
seat jail) plus :data:`CLI_DELTA` -- headless ``-p``, stream-json output with the prompt on
stdin as text, and ``--no-session-persistence`` -- and never ``--bare``. It runs in the
same ``_JailedSeat`` (jail, probe jail, staged clone), environment, descriptors and
teardown as the TUI; the jailed login proof ran before it (IF-0-CLAUDE-4).

Admission happens here, in the parent, on the CLI's own stdout. :class:`StreamAdmission`
reads every frame as it arrives and admits exactly one result:

* the first ``system/init`` must report ``apiKeySource == "none"`` (else the security code
  ``claude_seat_api_key_source``) for this run's session;
* exactly one ``result`` frame, ``success`` and not an error, for that session, with a
  conforming verdict, and the CLI exiting 0 -- anything else is
  ``claude_seat_result_unproven``. Nothing may follow that result: a further line, valid,
  malformed, partial or oversized, stops the run with the same code. No transcript, output
  file or assistant turn is salvaged;
* a stream past :data:`STREAM_CAP_BYTES`, a line past :data:`LINE_CAP_BYTES`, stderr past
  :data:`STDERR_CAP_BYTES`, invalid UTF-8, a line that opens a JSON value but does not parse,
  a duplicate key or nesting past :data:`NESTING_BOUND` in any ``system`` or ``result``
  frame, a result text that is not valid Unicode, a parser ``RecursionError`` or any other
  failure reading a frame, is ``claude_seat_stream_unsafe``;
* the seat token, in any encoding the jail's scan knows, anywhere in what the parent reads
  -- the raw stdout and stderr, and the result text it keeps -- is
  ``claude_seat_token_in_output``.

Observations (:mod:`claude_print_observations`) are bounded and metadata-only, and never
change admission. The selection is experimental and unqualified (§4a item 6).

``panel_invoker`` helpers are late-bound through the package facade (PANELSPLIT-compatible)
and none is changed. This module never imports the Agent SDK.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Callable, Mapping

from . import seat_jail as _seat_jail
from .claude_print_observations import ClaudePrintObservations
from .claude_seat_transport import RecordCitation

ADMITTED = True
#: §4a of the print-route record, as merged by agent-harness#1775 (the plan's input pin).
ACTIVATION = RecordCitation(
    "plans/decision-claude-print-subscription-route-20261008.md",
    "4a",
    "7af0fb700ef10d444a904b01169c8b08aa056ba25ca496c7adcca7c646852cdb",
    "agent-harness#1775",
)
TRANSPORT = "print"
#: The only argv tokens ``print`` adds to the jailed TUI command (§4a item 4).
CLI_DELTA: tuple[str, ...] = (
    "-p", "--verbose", "--output-format", "stream-json", "--input-format", "text",
    "--no-session-persistence",
)
#: The whole stdout stream the parent reads.
STREAM_CAP_BYTES = 64 << 20
#: One stream-json line.
LINE_CAP_BYTES = 16 << 20
#: JSON nesting in one frame.
NESTING_BOUND = 64
#: The CLI's stderr, which the parent reads only to scan.
STDERR_CAP_BYTES = 4 << 20

API_KEY_SOURCE = "claude_seat_api_key_source"
RESULT_UNPROVEN = "claude_seat_result_unproven"
STREAM_UNSAFE = "claude_seat_stream_unsafe"
TOKEN_IN_OUTPUT = "claude_seat_token_in_output"
#: The retry categories that mean the credential stopped being a working subscription.
AUTH_DRIFT = "claude_print_auth_drift"
_AUTH_DRIFT_ERRORS = frozenset({"authentication_failed", "billing_error", "oauth_org_not_allowed"})


@dataclass(frozen=True)
class ParsePolicy:
    """How one route parses a stream-json line before admission reads it. The parse happens
    once, here; a route that needs the frame afterwards takes the parsed object through
    :class:`StreamAdmission`'s ``on_frame`` and never reparses the line.

    :data:`PRINT_POLICY` is ``print``'s own (§4a items 4 and 5): a duplicate key refuses only
    in a ``system`` or ``result`` frame, and the token is scanned in the raw stream and the
    result text. A stricter route may refuse a duplicate key in every frame and scan every
    decoded key and string value (JSON escapes resolved), with ``frame_violation`` as the
    code for a frame only that policy refuses."""

    name: str
    duplicates_everywhere: bool = False
    scan_decoded: bool = False
    frame_violation: str = STREAM_UNSAFE


#: ``print``'s parse policy. It is the default, and print's admission does not change with it.
PRINT_POLICY = ParsePolicy("print")


def decoded_strings(value: object):
    """Every decoded key and string value of one parsed frame, JSON escapes resolved."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for key, child in item.items():
                yield key
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def _pi() -> ModuleType:
    return importlib.import_module(f"{__package__}.panel_invoker")


class _Unsafe(Exception):
    pass


def _nesting(raw: bytes, bound: int) -> int:
    """The bracket depth of one JSON text, outside strings, stopping past ``bound``."""
    depth = deepest = 0
    in_string = escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > deepest:
                deepest = depth
                if deepest > bound:
                    return deepest
        elif byte in (0x5D, 0x7D):
            depth -= 1
    return deepest


class StreamAdmission:
    """The parent-side reader of one jailed CLI's stream-json stdout.

    ``feed`` sees raw chunks as they arrive and returns True to stop the run at once (the
    runner then kills the process group). ``finish`` reads a final unterminated line. The
    admission predicates are :meth:`admitted` and :attr:`violation`.

    ``policy`` is the route's :class:`ParsePolicy` (``print``'s by default). ``on_frame``
    receives each frame's parsed object after admission read it, only while no violation
    stands -- the same object, so a route that forwards frames never parses a line twice."""

    def __init__(self, *, token: bytes, session_id: str,
                 observations: ClaudePrintObservations | None = None,
                 stream_cap: int | None = None, line_cap: int | None = None,
                 policy: ParsePolicy = PRINT_POLICY,
                 on_frame: Callable[[dict], None] | None = None) -> None:
        self._token = token
        self._forms = _seat_jail.secret_encodings(token)
        self._overlap = max(map(len, self._forms), default=1) - 1
        self._tail = b""
        self._err_tail = b""
        self.stderr_bytes = 0
        self._carry = bytearray()
        self._stream_cap = STREAM_CAP_BYTES if stream_cap is None else stream_cap
        self._line_cap = LINE_CAP_BYTES if line_cap is None else line_cap
        self.session_id = session_id
        self.observations = observations
        if not isinstance(policy, ParsePolicy):
            raise TypeError("policy must be a ParsePolicy")
        self.policy = policy
        self._on_frame = on_frame
        self._parsed: dict | None = None
        self.bytes = 0
        self.frames = 0
        self.violation: str | None = None
        self.init_seen = False
        self.api_key_source: str | None = None
        self.session_matches = False
        self.results = 0
        self.result_text: str | None = None
        self.result_sha256: str | None = None
        self.result_success = False

    # -- the raw channel -------------------------------------------------------------

    def _stop(self, code: str) -> bool:
        """Record ``code`` (the first violation stands, except that a token in the output
        always wins) and stop the run."""
        if self.violation is None or code == TOKEN_IN_OUTPUT:
            self.violation = code
        return True

    def feed(self, chunk: bytes) -> bool:
        if self.violation is not None:
            return True
        window = self._tail + chunk
        if any(form in window for form in self._forms):
            return self._stop(TOKEN_IN_OUTPUT)
        self._tail = window[-self._overlap:] if self._overlap else b""
        self.bytes += len(chunk)
        if self.bytes > self._stream_cap:
            return self._stop(STREAM_UNSAFE)
        self._carry.extend(chunk)
        while True:
            end = self._carry.find(b"\n")
            if end < 0:
                if self.results and self._carry.strip():
                    return self._stop(RESULT_UNPROVEN)  # nothing may follow the one result
                if len(self._carry) > self._line_cap:
                    return self._stop(STREAM_UNSAFE)
                break
            line = bytes(self._carry[:end])
            del self._carry[:end + 1]
            if self.results and line.strip():
                return self._stop(RESULT_UNPROVEN)
            if len(line) > self._line_cap:
                return self._stop(STREAM_UNSAFE)
            self._frame(line)
            if self.violation is not None:
                return True
        return False

    def feed_stderr(self, chunk: bytes) -> bool:
        """The CLI's stderr, scanned for the token across chunk boundaries and capped."""
        window = self._err_tail + chunk
        if any(form in window for form in self._forms):
            return self._stop(TOKEN_IN_OUTPUT)
        self._err_tail = window[-self._overlap:] if self._overlap else b""
        self.stderr_bytes += len(chunk)
        if self.stderr_bytes > STDERR_CAP_BYTES:
            return self._stop(STREAM_UNSAFE)
        return self.violation is not None

    def finish(self) -> None:
        if self.violation is None and self._carry:
            line = bytes(self._carry)
            self._carry.clear()
            if len(line) > self._line_cap:
                self._stop(STREAM_UNSAFE)
            else:
                self._frame(line)

    # -- one frame -------------------------------------------------------------------

    def _frame(self, raw: bytes) -> None:
        if not raw.strip():
            return
        self._parsed = None
        try:
            self._parse(raw)
        except (_Unsafe, RecursionError):
            self._stop(STREAM_UNSAFE)
        except Exception:  # any hostile value is a typed refusal, never an untyped failure
            self._stop(STREAM_UNSAFE)
        parsed, self._parsed = self._parsed, None
        if parsed is None or self.violation is not None or self._on_frame is None:
            return
        try:
            # The admission's own parse, handed on: the caller never reparses the line.
            self._on_frame(parsed)
        except Exception:
            self._stop(self.policy.frame_violation)

    def _parse(self, raw: bytes) -> None:
        duplicate = False

        def unique(pairs):
            nonlocal duplicate
            keys = [key for key, _value in pairs]
            if len(keys) != len(set(keys)):
                duplicate = True
            return dict(pairs)

        deep = _nesting(raw, NESTING_BOUND) > NESTING_BOUND
        try:
            text = raw.decode("utf-8", errors="strict")
            strict = True
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            strict = False
        if deep:
            # Too deep to parse safely: refused whatever the frame claims to be.
            raise _Unsafe("nesting")
        try:
            event = json.loads(text, object_pairs_hook=unique)
        except ValueError:
            if not strict:
                raise _Unsafe("utf-8") from None
            start = raw.find(b"{")
            if start > 0:
                try:
                    embedded = json.loads(raw[start:].decode("utf-8", errors="strict"))
                except (UnicodeDecodeError, ValueError):
                    embedded = None
                if isinstance(embedded, dict) and embedded.get("type") in ("system", "result"):
                    raise _Unsafe("malformed") from None
            if raw.lstrip()[:1] in (b"{", b"["):
                raise _Unsafe("malformed") from None  # a frame that does not parse
            return  # not a frame; it supplies nothing and admits nothing
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind in ("system", "result") and (duplicate or not strict):
            raise _Unsafe("frame")
        if not strict:
            raise _Unsafe("utf-8")
        if duplicate and self.policy.duplicates_everywhere:
            self._stop(self.policy.frame_violation)
            return
        if self.policy.scan_decoded and any(
                any(form in text.encode("utf-8", errors="surrogatepass") for form in self._forms)
                for text in decoded_strings(event)):
            self._stop(TOKEN_IN_OUTPUT)
            return
        self.frames += 1
        self._parsed = event
        if self.observations is not None:
            try:
                if duplicate:
                    self.observations.malformed("duplicate_key")
                else:
                    self.observations.event(event)
            except Exception:  # observations never change admission
                self.observations.malformed("frame_shape")
        subtype = event.get("subtype")
        if kind == "system" and subtype == "init":
            if self.init_seen or self.results:
                self.violation = RESULT_UNPROVEN
                return
            self.init_seen = True
            source = event.get("apiKeySource")
            self.api_key_source = source if isinstance(source, str) and len(source) <= 64 else None
            self.session_matches = event.get("session_id") == self.session_id
            if source != "none":
                self.violation = API_KEY_SOURCE
            return
        if kind == "system" and subtype == "api_retry":
            error = event.get("error")
            if error is not None and not isinstance(error, str):
                raise _Unsafe("retry error")  # a retry category is text; anything else is hostile
            if error in _AUTH_DRIFT_ERRORS:
                self.violation = AUTH_DRIFT
            return
        if kind == "result":
            self.results += 1
            if self.results > 1:
                self.violation = RESULT_UNPROVEN
                return
            text = event.get("result")
            self.result_success = (
                self.init_seen and subtype == "success" and event.get("is_error") is False
                and isinstance(text, str) and event.get("session_id") == self.session_id)
            if isinstance(text, str):
                # The text is scanned as the parent will keep it, not only as it was read.
                if _seat_jail.contains_secret(text.encode("utf-8", errors="surrogatepass"),
                                              self._token):
                    self._stop(TOKEN_IN_OUTPUT)
                    return
                try:
                    encoded = text.encode("utf-8")
                except UnicodeEncodeError:
                    raise _Unsafe("result text") from None
                self.result_text = text
                self.result_sha256 = sha256(encoded).hexdigest()

    def admitted(self, returncode: int) -> bool:
        """Every predicate: no violation, one proven init for this session with no key
        source, exactly one successful result for this session, and exit 0."""
        return (self.violation is None and self.init_seen and self.api_key_source == "none"
                and self.session_matches and self.results == 1 and self.result_success
                and self.result_text is not None and returncode == 0)

    def evidence(self) -> dict[str, object]:
        return {
            "claude_api_key_source": self.api_key_source if self.api_key_source == "none"
            else ("present" if self.api_key_source is not None else None),
            "claude_result_count": self.results,
            "claude_session_id_matches": self.session_matches,
            "claude_result_event_sha256": self.result_sha256,
            "claude_stream_bytes": self.bytes,
            "claude_stream_frames": self.frames,
        }


def print_command(jail: "_seat_jail.SeatJail", *, model: str | None, effort: str | None,
                  session_id: str, env: Mapping[str, str] | None,
                  session_name: str | None) -> list[str]:
    """The jailed TUI command plus :data:`CLI_DELTA` after its argv0, nothing else."""
    command = _pi()._broker_claude_tui_command(
        model=model, effort=effort, session_id=session_id, sandboxed=jail, env=env,
        session_name=session_name)
    if "--bare" in command:
        raise ValueError("the jailed print command never uses --bare")
    return [command[0], *CLI_DELTA, *command[1:]]


def entrypoint_at_boundary(env: Mapping[str, str]) -> str:
    """``CLAUDE_CODE_ENTRYPOINT`` as the CLI process receives it, as a short slug."""
    value = env.get("CLAUDE_CODE_ENTRYPOINT")
    if value is None:
        return "unset"
    return value if value.isascii() and value.replace("-", "").replace("_", "").isalnum() \
        and len(value) <= 32 else "other"


def run_jailed(
    seat: object,
    *,
    timeout_s: int,
    backstop_s: int,
    model: str | None,
    effort: str | None,
    prompt: str,
    broker_evidence: dict[str, object] | None,
    env: Mapping[str, str] | None = None,
    failure_detail_sink: list | None = None,
    quiescence_latch: object | None = None,
    review_monitor: object | None = None,
    session_name: str | None = None,
    **_unused: object,
) -> tuple[str, str]:
    """The ``print`` transport on a prepared, login-proven jailed seat. Returns
    ``(status, text)``; tears the seat down whatever happens."""
    pi = _pi()
    jail = seat.jail  # type: ignore[attr-defined]
    requested = model or pi.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["claude"]
    session_id = str(uuid.uuid4())
    stream: StreamAdmission | None = None
    run = None
    timed_out = False
    try:
        if review_monitor is not None and review_monitor.cancel.is_set():  # type: ignore[attr-defined]
            return "UNAVAILABLE", "review_operation_cancelled"
        command = print_command(jail, model=model, effort=effort, session_id=session_id,
                                env=env, session_name=session_name)
        transport = pi._BROKER_CLAUDE_DIRECT_REQUEST + prompt
        stall_s = pi._broker_claude_stall_threshold(prompt, backstop_s)
        pi._record_broker_provider_evidence(
            broker_evidence, harness="claude", model=requested, command=command, prompt=prompt,
            cwd=Path(_seat_jail.SEAT_TREE),
            env={key: (_seat_jail.TOKEN_FD_PLACEHOLDER if key == _seat_jail.CLAUDE_TOKEN_FD_ENV
                       else value) for key, value in jail.env.items()},
            prompt_transport="stdin", stdin_prompt=True,
            no_tool_controls=pi._JAILED_CLAUDE_TOOL_CONTROLS, transport_payload=transport,
            transport_metadata={
                "provider_task_request_delivery": "plain_text_before_stdin_prompt",
                "provider_task_request_sha256": sha256(
                    pi._BROKER_CLAUDE_DIRECT_REQUEST.encode()).hexdigest(),
                "provider_task_request_bytes": len(pi._BROKER_CLAUDE_DIRECT_REQUEST.encode()),
            },
            redacted_argv_values={session_id: "<CLAUDE_SESSION_ID>",
                                  **({session_name: "<CLAUDE_SESSION_NAME>"} if session_name else {})},
        )
        if broker_evidence is not None:
            broker_evidence.update({
                "provider_input_mode": "pointer",
                "provider_input_inline": False,
                "provider_cwd_class": "seat_jail_tree",
                "provider_cwd_sha256": sha256(
                    f"{_seat_jail.SEAT_TREE}\0{jail.profile_digest}".encode()).hexdigest(),
                "sandbox_filesystem_confined": True,
                "seat_jail_profile_id": jail.profile_id,
                "seat_jail_profile_digest": jail.profile_digest,
                "seat_jail_filter_sha256": jail.filter_digest,
                "seat_jail_owner_argv_shape": tuple(jail.redacted_owner()),
                "jail_profile_digest": jail.profile_digest,
                "claude_transport": TRANSPORT,
                "claude_route": TRANSPORT,
                "claude_code_entrypoint": entrypoint_at_boundary(jail.env),
                "claude_session_id_sha256": sha256(session_id.encode()).hexdigest(),
                "claude_session_resume_forbidden": True,
                "claude_session_persistence": False,
                "provider_liveness_profile": pi._BROKER_CLAUDE_STALL_PROFILE,
                "provider_liveness_stall_threshold_s": stall_s,
                "provider_liveness_prompt_bytes": len(prompt.encode("utf-8", errors="strict")),
            })
        pi._record_executable_dependency_evidence(broker_evidence, jail)
        observations = ClaudePrintObservations(
            session_id, requested, lambda text: _classify_error(pi, text))
        stream = StreamAdmission(token=seat.token, session_id=session_id,  # type: ignore[attr-defined]
                                 observations=observations)
        try:
            run = pi._run_leg_with_liveness(
                command, cwd=Path(_seat_jail.SEAT_TREE), env=dict(jail.env),
                deadline_s=float(max(1, int(backstop_s))), stall_threshold_s=stall_s,
                input_text=transport, stdout_guard=stream.feed,
                stderr_guard=stream.feed_stderr,
                seat_jail=jail, probe_jail=seat.probe_jail,  # type: ignore[attr-defined]
                **({"quiescence_latch": quiescence_latch} if quiescence_latch is not None else {}),
                **({"review_monitor": review_monitor} if review_monitor is not None else {}),
            )
        except subprocess.TimeoutExpired:
            timed_out = True
        stream.finish()
    finally:
        pi._cleanup_jailed_seat(seat, primary=sys.exception())
    return _outcome(pi, stream, run, timed_out, broker_evidence, failure_detail_sink,
                    seat=seat, review_monitor=review_monitor)


def _classify_error(pi: ModuleType, text: str) -> str:
    try:
        return str(pi._leg_failure_kind(1, "", text) or "unknown")
    except Exception:
        return "unknown"


def _outcome(pi, stream, run, timed_out, broker_evidence, sink, *, seat,
             review_monitor=None) -> tuple[str, str]:
    def fail(code: str, status: str = "DEGRADED") -> tuple[str, str]:
        if sink is not None:
            sink.append(pi._LegFailure(template=code))
        return status, ""

    if stream is None:
        return fail(RESULT_UNPROVEN)
    stderr = (getattr(run, "stderr", "") or "") if run is not None else ""
    if _seat_jail.contains_secret(stderr.encode("utf-8", errors="replace"), seat.token):
        stream.violation = TOKEN_IN_OUTPUT
    if broker_evidence is not None:
        broker_evidence.update(stream.evidence())
        if stream.observations is not None:
            broker_evidence["claude_item7_diagnostics"] = stream.observations.snapshot()
    if stream.violation == TOKEN_IN_OUTPUT:
        _admission(broker_evidence, "refused", TOKEN_IN_OUTPUT)
        return fail(TOKEN_IN_OUTPUT)
    if stream.violation is not None:
        _admission(broker_evidence, "refused", stream.violation)
        return fail(stream.violation)
    if timed_out:
        _admission(broker_evidence, "timed_out", RESULT_UNPROVEN)
        return fail(RESULT_UNPROVEN, "TIMEOUT")
    # The monitor's own cancel event, never text the CLI could write, means cancelled.
    if review_monitor is not None and review_monitor.cancel.is_set():
        return "UNAVAILABLE", "review_operation_cancelled"
    returncode = int(getattr(run, "returncode", 1))
    if not stream.admitted(returncode):
        _admission(broker_evidence, "absent", RESULT_UNPROVEN)
        return fail(RESULT_UNPROVEN)
    text = (stream.result_text or "").strip()
    if _seat_jail.contains_secret(text.encode("utf-8", errors="surrogatepass"), seat.token):
        _admission(broker_evidence, "refused", TOKEN_IN_OUTPUT)
        return fail(TOKEN_IN_OUTPUT)
    status = pi._classify_leg(returncode, text, "claude_print_result", "review")
    if status != "OK":
        _admission(broker_evidence, "absent", RESULT_UNPROVEN)
        return fail(RESULT_UNPROVEN)
    _admission(broker_evidence, "admitted", None)
    return "OK", text


def _admission(evidence: dict[str, object] | None, outcome: str, code: str | None) -> None:
    if evidence is not None:
        evidence["claude_admission"] = {"outcome": outcome, "code": code or "none"}
