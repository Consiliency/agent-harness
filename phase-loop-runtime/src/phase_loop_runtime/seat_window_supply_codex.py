"""Codex's window supplier (FIRSTSEAT amendment K-1, contract r4 §10.B).

It registers Codex's window data on import (§4.2) and supplies the §4.1 protocol names
for a Codex row window. Codex code is imported, never edited: the profile, rows, argv,
credential copy and stream vocabulary are CODEX's (IF-0-CODEX-1 to IF-0-CODEX-5).

The expired-copy control ages only the copy's unsigned ``last_refresh``. Its intended
refusal (§10) is the CLI's token-endpoint attempt, denied at the earliest point the
production ``codex`` allowlist permits (a named ``CONNECT auth.openai.com`` deny, or the
stricter POST form), before any model request, in a complete fenced stream, with the CLI
ending in a typed refusal.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from types import MappingProxyType
from typing import Sequence

from .seat_profiles import WINDOW_BOARD_FIELDS, WindowVendorData, register_window_data

#: The K-1 contract (``plans/artifacts/seats-window-kit-k1-contract.md``), as the amendment
#: pins it. Every non-Gemini vendor binds this file (§3).
K1_CONTRACT_SHA256 = "12a7d96e639846c2f3868434ca1faca837113614ca138c866f2b69592c20c3b2"

LAUNCH_KINDS = frozenset({
    "help", "tree_control", "runtime_control", "credentialed_tree_control",
    "credentialed_runtime_control", "measured", "expired_copy",
})
CREDENTIAL_KINDS = frozenset({
    "credentialed_tree_control", "credentialed_runtime_control", "measured", "expired_copy",
})
_NONE_KINDS = frozenset({"help", "tree_control", "runtime_control"})
_TREE_KINDS = frozenset({"tree_control", "credentialed_tree_control"})
#: §10.B's fixture: the copy's ``last_refresh`` is set this many days in the past.
AGED_REFRESH_DAYS = 60

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
# The A-C1 surface: kinds, the aged copy, argv, stream facts, terminal, token endpoint.
# --------------------------------------------------------------------------------------

def credential_mode(kind: str) -> str:
    if kind not in LAUNCH_KINDS:
        raise ValueError("contract_bug")
    if kind == "expired_copy":
        return "expired"
    return "none" if kind in _NONE_KINDS else "live"


def aged_copy(copy):
    """§10.B's expired copy: the production copy with only ``last_refresh`` moved
    :data:`AGED_REFRESH_DAYS` into the past. The JWT and the empty refresh token are kept."""
    from .seat_codex_credential import CodexSeatCopy
    if not isinstance(copy, CodexSeatCopy):
        raise TypeError("copy must be a CodexSeatCopy")
    document = json.loads(copy.data)
    if not isinstance(document, dict) or "last_refresh" not in document:
        raise ValueError("contract_bug")
    aged = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=AGED_REFRESH_DAYS)
    document["last_refresh"] = aged.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return dataclasses.replace(
        copy, data=json.dumps(document, sort_keys=True, indent=2).encode("utf-8"))


copy_transform = aged_copy


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
    if getattr(observation, "timed_out", False):
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
    if events == () and status != "SUCCESS":
        return "not_ready"  # the CLI failed before its credential path: no request at all
    if status not in {"SUCCESS", "FAILURE"}:
        return "stream_incomplete"
    tokens = [event for event in events if token_endpoint(event)]
    models = [event for event in events if _model_request(event)]
    if status == "SUCCESS":
        if getattr(observation, "model_turn", None) is True and not tokens:
            return "completed"
        return "other_failure"
    if (tokens and not models and all(event.decision == "deny" for event in tokens)
            and getattr(observation, "model_turn", None) is not True):
        return ("refused_intended" if getattr(observation, "kind", None) == "expired_copy"
                else "auth_refused")
    return "other_failure"
