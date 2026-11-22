"""Codex's window supplier (FIRSTSEAT amendment K-1, contract r4 §10.B).

It registers Codex's window data on import (§4.2) and supplies the §4.1 protocol names
for a Codex row window. Codex code is imported, never edited: the profile, rows, argv,
credential copy and stream vocabulary are CODEX's (IF-0-CODEX-1 to IF-0-CODEX-5).

The expired-copy control (contract r5.2 §10.B, the Codex exception to §10) edits exactly
one field of the production copy: the access token's ``exp``, set an hour into the past.
0.167.0 refreshes on that ``exp`` alone, and the production ``codex`` allowlist refuses the
refresh at ``CONNECT auth.openai.com``. Its intended refusal is that named denial, before any
model request, in a complete fenced stream, with no token-host request, no allowed request
(in the loopback fixture: every later model request carrying the installed expired bearer)
and no credential change, whatever the CLI's exit.

Until the OI-1 fence lands, a Codex row window is held (:data:`ROW_WINDOW_HOLD`).
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import re
import time
from types import MappingProxyType
from typing import Mapping, Sequence

from .seat_profiles import WINDOW_BOARD_FIELDS, WindowVendorData, register_window_data

#: The K-1 contract (``plans/artifacts/seats-window-kit-k1-contract.md``), as the amendment
#: pins it. Every non-Gemini vendor binds this file (§3).
K1_CONTRACT_SHA256 = "aa30ce0a2f947fd004476ac62f1c964c57a1e6554cc273e16366c92a2088e967"

LAUNCH_KINDS = frozenset({
    "help", "tree_control", "runtime_control", "credentialed_tree_control",
    "credentialed_runtime_control", "measured", "expired_copy",
})
CREDENTIAL_KINDS = frozenset({
    "credentialed_tree_control", "credentialed_runtime_control", "measured", "expired_copy",
})
_NONE_KINDS = frozenset({"help", "tree_control", "runtime_control"})
_TREE_KINDS = frozenset({"tree_control", "credentialed_tree_control"})
#: r5.2 §10.B: the expired copy's access ``exp`` is the transform clock minus this.
EXPIRED_ACCESS_MARGIN_S = 3600
#: r5.2 §10.B (B1): the typed row-ready code every Codex row window refuses with, before
#: any claim, preflight, jail or proxy, until the OI-1 fence lane lands and lifts it.
ROW_WINDOW_HOLD = "codex_expired_leg_unfenced"

TOKEN_HOST, TOKEN_PATH = "auth.openai.com", "/oauth/token"
MODEL_HOST, MODEL_PATH = "chatgpt.com", "/backend-api/codex/responses"

_SURFACE = frozenset({"not_loaded", "loaded", "unavailable"})

CODEX_WINDOW_DATA = register_window_data(WindowVendorData(
    leg="codex",
    vendor="codex",
    record_fields=MappingProxyType({"canonical": "canonical_codex", "route": "codex_route"}),
    board_fields=WINDOW_BOARD_FIELDS,
    route_literal="jailed",
    containment_outcomes=MappingProxyType({
        "credential_scope": frozenset({"pass", "codex_seat_token_scope_excess", "unavailable"}),
        "refresh_detection": frozenset({
            "pass", "codex_seat_token_refreshed_in_jail", "unavailable"}),
        "project_settings": _SURFACE, "hooks": _SURFACE, "mcp_servers": _SURFACE,
        "provider_overrides": _SURFACE,
    }),
    control_launcher="window_control_launch",
    board_launcher="window_board_launch",
    model_leg="codex",
    dependency_provider="codex",
    co_seats=frozenset({"claude", "gemini", "grok"}),
    default=False,
    supplier="seat_window_supply_codex",
    contract_sha256=K1_CONTRACT_SHA256,
    windows=frozenset({"row"}),
    launch_kinds=LAUNCH_KINDS,
    credential_kinds=CREDENTIAL_KINDS,
    launch_cap=len(CREDENTIAL_KINDS) + 1,
))

#: Codex's help gate has the nested plugin form only (§10.B).
plugin_forms = ("nested",)


# --------------------------------------------------------------------------------------
# The A-C1 surface: kinds, the expired access copy, argv, stream facts, terminal, token
# endpoint.
# --------------------------------------------------------------------------------------

def credential_mode(kind: str) -> str:
    if kind not in LAUNCH_KINDS:
        raise ValueError("contract_bug")
    if kind == "expired_copy":
        return "expired"
    return "none" if kind in _NONE_KINDS else "live"


def expired_access_copy(copy, *, now: int | None = None):
    """r5.2 §10.B: the production copy with exactly one field changed, the access token's
    ``exp``, set to the transform's UTC clock (integer Unix seconds) minus
    :data:`EXPIRED_ACCESS_MARGIN_S`. The header and signature segments are kept byte for
    byte and the payload is re-encoded as unpadded base64url. The ID token, ``last_refresh``
    and the empty ``refresh_token`` are unchanged. ``tokens_sha256`` is recomputed over the
    edited tokens, ``secrets`` gains the edited access token, ``expires_at`` is kept."""
    from .seat_codex_credential import CodexSeatCopy, _tokens_sha256
    if not isinstance(copy, CodexSeatCopy):
        raise TypeError("copy must be a CodexSeatCopy")
    try:
        document = json.loads(copy.data)
        tokens = document["tokens"]
        header, payload, signature = tokens["access_token"].split(".")
        claims = json.loads(base64.urlsafe_b64decode(
            payload + "=" * (-len(payload) % 4)).decode("utf-8"))
    except (TypeError, KeyError, ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("contract_bug") from exc
    if not isinstance(claims, dict) or type(claims.get("exp")) is not int:
        raise ValueError("contract_bug")
    clock = int(time.time()) if now is None else int(now)
    claims["exp"] = clock - EXPIRED_ACCESS_MARGIN_S
    edited_payload = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")).rstrip(b"=").decode("ascii")
    edited = ".".join((header, edited_payload, signature))
    tokens = {**tokens, "access_token": edited}
    document = {**document, "tokens": tokens}
    return dataclasses.replace(
        copy, data=json.dumps(document, sort_keys=True, indent=2).encode("utf-8"),
        secrets=(*copy.secrets, edited.encode("utf-8")), tokens_sha256=_tokens_sha256(tokens))


copy_transform = expired_access_copy


def launch_command(kind: str, *, qualification_input=None, model: str,
                   plugin_paths: Sequence[str] = ()) -> tuple[tuple[str, ...], ...]:
    """Every argv one launch spawns: the production Codex command (its prompt on stdin,
    supplied by the kit), run from the tree for the tree kinds; ``help`` starts no turn."""
    from .seat_codex_runtime import CODEX_RUNTIME_ROOT
    from .seat_profile_codex import jailed_codex_command
    from .seat_route_contract import ArgvInputs
    if kind not in LAUNCH_KINDS:
        raise ValueError("contract_bug")
    binary = f"{CODEX_RUNTIME_ROOT}/bin/codex"
    if kind == "help":
        return ((binary, "exec", "--help"),)
    argv = list(jailed_codex_command(ArgvInputs(binary, model=model)))
    if kind in _TREE_KINDS:
        argv[argv.index("--cd") + 1] = "/seat/tree"
    return (tuple(argv),)


def stream_facts(raw_stdout: str):
    """``(status, model_turn, tool_steps, subagent_steps)`` of the CLI's ``--json`` stream.
    Anything incomplete, malformed or outside IF-0-CODEX-4's vocabulary is ``NONE``."""
    from .seat_codex_evidence import CODEX_TOOL_EVENTS
    if not isinstance(raw_stdout, str) or not raw_stdout.strip():
        return "NONE", None, None, None
    if not raw_stdout.endswith("\n"):
        return "NONE", None, None, None
    started = completed = failed = errored = model_turn = False
    tools = 0
    try:
        for line in raw_stdout.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict) or event.get("type") not in CODEX_TOOL_EVENTS:
                raise ValueError("unknown event")
            if completed or failed:
                raise ValueError("event after the terminal event")
            name = event["type"]
            if name == "turn.started":
                if started:
                    raise ValueError("second turn")
                started = True
            elif name in {"turn.completed", "turn.failed"}:
                if not started:
                    raise ValueError("terminal event without a turn")
                completed, failed = name == "turn.completed", name == "turn.failed"
            elif name == "error":
                errored = True
            elif name == "item.completed":
                item = event.get("item")
                if not isinstance(item, dict):
                    raise ValueError("malformed item")
                model_turn = model_turn or item.get("type") == "agent_message"
                tools += int(item.get("type") == "command_execution")
    except (TypeError, ValueError):
        return "NONE", (True if model_turn else None), None, None
    if completed:
        return "SUCCESS", model_turn, tools, 0
    if failed or errored:
        return "FAILURE", model_turn, tools, 0
    return "NONE", (True if model_turn else None), None, None


def token_endpoint(event) -> bool:
    """The CLI's token endpoint (``https://auth.openai.com/oauth/token``): the POST itself,
    or its named CONNECT, which the production allowlist refuses before any request."""
    if getattr(event, "host", None) != TOKEN_HOST:
        return False
    method, path = getattr(event, "method", None), getattr(event, "path", None)
    return (method == "POST" and path == TOKEN_PATH) or (method == "CONNECT" and path is None)


def _model_request(event) -> bool:
    return (getattr(event, "method", None) == "POST"
            and getattr(event, "host", None) == MODEL_HOST
            and getattr(event, "path", None) == MODEL_PATH)


def _named_denial(event) -> bool:
    """The production named observation of the refused refresh (r5.2 §10.B)."""
    return (getattr(event, "method", None) == "CONNECT"
            and getattr(event, "host", None) == TOKEN_HOST
            and getattr(event, "path", "") is None
            and getattr(event, "decision", None) == "deny")


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _expired_refused(observation, events) -> bool:
    """r5.2 §10.B and the president's E2 ruling: the expired leg's ``refused_intended``,
    decided on its complete fenced stream whatever the CLI's exit:

    * every token-host event is the named ``CONNECT`` denial (any request event to the token
      host means the CONNECT was tunnelled), and there is at least one;
    * no model request comes before the first denial;
    * the pre-teardown read shows no credential change (``scan["refresh"] == "pass"``);
    * production (no bearer proof): no allowed request of any kind;
    * the loopback fixture (``bearer_proof``): every model request was allowed and answered
      with a recorded ``Authorization`` sha256 equal to the installed expired bearer's."""
    tokens = [index for index, event in enumerate(events)
              if getattr(event, "host", None) == TOKEN_HOST]
    if not tokens or not all(_named_denial(events[index]) for index in tokens):
        return False
    models = [index for index, event in enumerate(events) if _model_request(event)]
    if any(index < tokens[0] for index in models):
        return False
    scan = getattr(observation, "scan", None)
    if not isinstance(scan, Mapping) or scan.get("refresh") != "pass":
        return False
    proof = getattr(observation, "bearer_proof", None)
    if proof is None:
        return not any(event.decision == "allow" for event in events)
    if not isinstance(proof, Mapping):
        return False
    expected, digests = proof.get("expected_sha256"), proof.get("model_requests")
    if not isinstance(expected, str) or _DIGEST.fullmatch(expected) is None:
        return False
    if not isinstance(digests, (list, tuple)) or len(digests) != len(models):
        return False
    return (all(events[index].decision == "allow" for index in models)
            and all(digest == expected for digest in digests))


def _leg_events(stream):
    """The leg window's events of a complete stream, else ``None``."""
    if stream is None or not getattr(stream, "final", False) or getattr(
            stream, "protocol_error", True) or getattr(stream, "outside_events", ()):
        return None
    windows = [window for window in getattr(stream, "windows", ()) if window.label == "leg"]
    if len(windows) != 1 or not (windows[0].start_acked and windows[0].end_acked):
        return None
    return tuple(windows[0].events)


def terminal(observation) -> str:
    """§5.5's closed class for one launch result."""
    error = getattr(observation, "error", None)
    timed_out = bool(getattr(observation, "timed_out", False))
    # r5.2 / E2: the expired leg's stream decides first, whatever the CLI's exit, a stop at
    # the launch's own deadline (the kit records it as ``launch_failed``) included. A jail
    # or proxy failure, an incomplete stream or any other error never reaches it.
    if (getattr(observation, "kind", None) == "expired_copy"
            and (error is None or (error == "launch_failed" and timed_out))):
        events = _leg_events(getattr(observation, "stream", None))
        if events is not None and _expired_refused(observation, events):
            return "refused_intended"
    if timed_out:
        return "timeout"
    if error in {"proxy_unavailable", "fence_unacknowledged"}:
        return "proxy_failure"
    if error in {"jail_unavailable", "watch_unavailable", "bridge_wait_timeout"}:
        return "jail_failure"
    if error == "credential_unavailable":
        return "not_ready"
    if error is not None:
        return "other_failure"
    status = getattr(observation, "status", "NONE")
    events = _leg_events(getattr(observation, "stream", None))
    if events is None:
        return "stream_incomplete"
    tokens = [event for event in events if token_endpoint(event)]
    models = [event for event in events if _model_request(event)]
    if (status != "SUCCESS" and not tokens and not models
            and not any(event.decision == "allow" for event in events)):
        # §5.5/§10.B (SL-6 ruling 3): the CLI ended by itself (a timeout is classed above)
        # before its credential path: no token-host event, no model request and no allowed
        # request. Denied CONNECTs to other hosts are not the credential path.
        return "not_ready"
    if status not in {"SUCCESS", "FAILURE"}:
        return "stream_incomplete"
    if status == "SUCCESS":
        if getattr(observation, "model_turn", None) is True and not tokens:
            return "completed"
        return "other_failure"
    if (getattr(observation, "kind", None) != "expired_copy" and tokens and not models
            and all(event.decision == "deny" for event in tokens)
            and getattr(observation, "model_turn", None) is not True):
        return "auth_refused"
    return "other_failure"
