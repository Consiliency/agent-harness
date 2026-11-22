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
    # A CLI ended by a signal (not the launch's own deadline) is a process failure: it never
    # reaches refused_intended or not_ready, whatever its stream shows.
    exit_code = getattr(observation, "exit_code", None)
    if not timed_out and type(exit_code) is int and (exit_code < 0 or exit_code >= 128):
        return "other_failure"
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


# --------------------------------------------------------------------------------------
# SL-6.5: the I-4 rows and host paths, the scope, refresh and secret outcomes, the bracket.
# FIRSTSEAT's I-4/I-13 helpers are imported, never edited; Codex's paths are its own.
# --------------------------------------------------------------------------------------

#: §10.B rows: every CODEX tree row at the tree, workdir and home locations (home less the
#: ``.codex/`` rows, which live at ``provider_config``); the ``.codex/`` rows re-rooted at
#: ``provider_config`` (``/seat/home/.codex``, the jail's ``CODEX_HOME``) plus
#: ``provider_config:AGENTS.md``; and the home row ``home:.codex/config.toml``. The home row
#: is the file the CLI's own config lives in; it is observed, never planted (it is the same
#: host file as ``provider_config:config.toml``).
HOME_ROW = ("home", ".codex/config.toml", "project_settings")
_PROVIDER_CONFIG_EXTRA = (("AGENTS.md", "provider_overrides"),)


def _layout_spec(window) -> tuple[tuple[str, str, str], ...]:
    from .seat_profile_codex import CODEX_TREE_ROWS, CODEX_WINDOW_ROWS
    if window is not CODEX_WINDOW_ROWS and window != CODEX_WINDOW_ROWS:
        raise ValueError("contract_bug")
    rows = [("tree", path, role) for path, role in CODEX_TREE_ROWS]
    rows += [("workdir", path, role) for path, role in CODEX_TREE_ROWS]
    rows += [("home", path, role) for path, role in CODEX_TREE_ROWS
             if not path.startswith(".codex/")]
    rows += [("provider_config", path.removeprefix(".codex/"), role)
             for path, role in CODEX_TREE_ROWS if path.startswith(".codex/")]
    rows += [("provider_config", path, role) for path, role in _PROVIDER_CONFIG_EXTRA]
    rows.append(HOME_ROW)
    return tuple(rows)


def plant_layout(*, plugin_form: str, window=None):
    """The §10.B plant layout, with FIRSTSEAT's row, nonce and canary shapes."""
    import secrets
    from . import seat_jail_qualification as jailq
    from .seat_profile_codex import CODEX_WINDOW_ROWS
    if plugin_form not in plugin_forms:
        raise ValueError("plugin_form must be nested")
    spec = _layout_spec(CODEX_WINDOW_ROWS if window is None else window)
    rows, canaries = [], {surface: [] for surface in jailq._SURFACES}
    for location, relative, role in spec:
        nonce = secrets.token_hex(16)
        rows.append(jailq.PlantRow(row_id=f"{location}:{relative}", location=location,
                                   role=role, nonce=nonce))
        if role == "mcp_servers":
            canaries[role].append(f"{nonce}.invalid")
    frozen = {surface: tuple(values) for surface, values in canaries.items()}
    identity = {"rows": [[row.row_id, row.location, row.role, row.nonce] for row in rows],
                "canary_hosts": frozen, "plugin_form": plugin_form}
    return jailq.PlantLayout(rows=tuple(rows), canary_hosts=MappingProxyType(frozen),
                             plugin_form=plugin_form, layout_sha256=jailq._digest(identity))


def _layout_complete(layout) -> bool:
    from . import seat_jail_qualification as jailq
    from .seat_profile_codex import CODEX_WINDOW_ROWS
    if not isinstance(layout, jailq.PlantLayout) or layout.plugin_form not in plugin_forms:
        return False
    expected = set(_layout_spec(CODEX_WINDOW_ROWS))
    try:
        observed = {(row.location, jailq._row_parts(row.row_id)[1], row.role)
                    for row in layout.rows}
    except (AttributeError, jailq.PlantLayoutRefused, TypeError):
        return False
    identity = {"rows": [[row.row_id, row.location, row.role, row.nonce] for row in layout.rows],
                "canary_hosts": {surface: tuple(layout.canary_hosts.get(surface, ()))
                                 for surface in jailq._SURFACES},
                "plugin_form": layout.plugin_form}
    return (observed == expected and len(layout.rows) == len(expected)
            and len({row.nonce for row in layout.rows}) == len(layout.rows)
            and layout.layout_sha256 == jailq._digest(identity))


def build_qualification_input(layout, base):
    """One disposable, committed tree input outside this repository, with the tree rows
    planted by FIRSTSEAT's own plant writer."""
    import secrets
    from pathlib import Path
    from . import seat_jail_qualification as jailq
    if not _layout_complete(layout):
        raise jailq.PlantLayoutRefused("qualification input has an incomplete plant layout")
    base = Path(base).resolve()
    try:
        base.relative_to(jailq._repo_root())
    except ValueError:
        pass
    else:
        raise ValueError("qualification input must be outside this repository")
    base.mkdir(parents=True, exist_ok=True)
    repo = base / f"qualification-input-{secrets.token_hex(8)}"
    repo.mkdir(mode=0o700)
    for row in layout.rows:
        if row.location == "tree":
            relative = jailq._row_parts(row.row_id)[1]
            jailq._write_plant(repo, row, relative, layout.plugin_form,
                               command_path=f"/seat/tree/{relative}.inert")
    (repo / jailq.WINDOW_READ_PATH).write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    (repo / jailq.WATCH_OPEN_SENTINEL).write_text("watch sentinel\n", encoding="utf-8")
    jailq._write_executable(repo / jailq.WATCH_EXEC_SENTINEL, secrets.token_hex(16))
    jailq._git(repo, "init", "-q")
    jailq._git(repo, "add", "-A")
    jailq._git(repo, "commit", "-qm", "qualification input")
    import subprocess
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    return jailq.QualificationInput(repo=repo, commit=commit, layout=layout)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CodexHostPathMap:
    """Where a Codex seat's jailed locations live on the host."""

    tree: object
    seat_home: object
    provider_config: object
    seat_out: object
    delivered_credential: object | None


def host_path_map(seat, *, credential: bool):
    from . import seat_codex_credential as cred, seat_jail
    home = seat.seat_dir / seat_jail.HOST_HOME_DIRNAME
    return CodexHostPathMap(
        tree=seat.review_dir / seat_jail.HOST_TREE_DIRNAME, seat_home=home,
        provider_config=home / ".codex", seat_out=seat.seat_dir / seat_jail.HOST_OUT_DIRNAME,
        delivered_credential=home / cred.SEAT_AUTH_RELPATH if credential else None)


def _host_target(paths, location: str, relative: str):
    relative = relative.rstrip("/")
    if location == "tree":
        return paths.tree / relative, paths.tree
    if location == "workdir":
        return paths.seat_home / "workspace" / relative, paths.seat_home
    if location == "provider_config":
        return paths.provider_config / relative, paths.seat_home
    return paths.seat_home / relative, paths.seat_home


def _jail_root(location: str) -> str:
    return {"tree": "/seat/tree", "workdir": "/seat/home/workspace",
            "provider_config": "/seat/home/.codex"}.get(location, "/seat/home")


def seed_runtime_plants(layout, paths) -> None:
    """Plant the non-tree rows at the host paths backing their jailed locations; the home
    row is observed, not planted."""
    from . import seat_jail_qualification as jailq
    if not _layout_complete(layout):
        raise jailq.PlantLayoutRefused("runtime input has an incomplete plant layout")
    targets, seen = [], set()
    for row in layout.rows:
        relative = jailq._row_parts(row.row_id)[1]
        if row.location == "tree" or (row.location, relative, row.role) == HOME_ROW:
            continue
        target, boundary = _host_target(paths, row.location, relative)
        if target in seen or not jailq._no_symlink_ancestor(target, boundary):
            raise jailq.PlantLayoutRefused("runtime plant layout is not one-to-one")
        seen.add(target)
        targets.append((row, relative, target))
    for row, relative, target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        jailq._write_plant(target.parent, row,
                           target.name + ("/" if relative.endswith("/") else ""),
                           layout.plugin_form,
                           command_path=f"{_jail_root(row.location)}/{relative.rstrip('/')}.inert",
                           form_relative=relative)


def _proxy_secret(seat) -> tuple[bytes, ...]:
    import urllib.parse
    proxy = getattr(seat.jail, "env", {}).get("HTTPS_PROXY", "")
    password = urllib.parse.urlsplit(proxy).password if proxy else None
    return (password.encode("utf-8"),) if password else ()


def scan_secrets(seat) -> tuple[bytes, ...]:
    """The copy's secrets and the proxy credential; the proxy credential alone for a seat
    with no copy (``none``)."""
    copy = getattr(seat, "codex_copy", None)
    return (*(copy.secrets if copy is not None else ()), *_proxy_secret(seat))


def measure_credential_scope(seat) -> str:
    """§10.B: the scope via ``scope_problem``, on the host, with no issuer call."""
    from . import seat_codex_credential as cred
    copy = getattr(seat, "codex_copy", None)
    if copy is None:
        return "unavailable"
    return cred.scope_problem(copy.data) or "pass"


def refresh_detected(seat) -> str:
    """§10.B: the seat's copy, read back in H before teardown (as the production Codex leg
    reads it), compared with the installed copy. A removed copy is a credential event; a
    read that fails otherwise is ``unavailable``."""
    from . import seat_codex_credential as cred, seat_jail, seat_uid
    copy = getattr(seat, "codex_copy", None)
    if copy is None:
        return "unavailable"
    try:
        observed = seat_uid.read_in_h(seat.holder_pid, str(seat.seat_dir / seat_jail.HOST_HOME_DIRNAME),
                                      cred.SEAT_AUTH_RELPATH, cred.AUTH_CAP_BYTES)
    except seat_uid.SeatObjectMissing:
        return "codex_seat_token_refreshed_in_jail"
    except Exception:
        return "unavailable"
    return "codex_seat_token_refreshed_in_jail" if cred.tokens_changed(copy, observed) else "pass"


def bracket_steps():
    """The bracket for a Codex seat: FIRSTSEAT's network-refusal rows, run in the Codex jail
    (every probed host is outside the ``codex`` allowlist)."""
    from . import seat_jail_qualification as jailq
    return jailq.run_bracket


# --------------------------------------------------------------------------------------
# The containment watch and reducer (I-13). FIRSTSEAT's are Gemini-shaped (its provider
# config, issuer and token endpoints), so Codex does not reuse them. Until Codex's own land
# they refuse: a Codex row window can never record a passing containment result (and the
# B1 hold keeps any Codex row window from starting).
# --------------------------------------------------------------------------------------

def __getattr__(name: str):
    if name in {"ContextBinding", "ContainmentInputs"}:
        from . import seat_jail_qualification as jailq
        return getattr(jailq, name)
    raise AttributeError(name)


def arm_watch(layout, paths, *, kind):
    from . import seat_jail_qualification as jailq
    raise jailq.WatchUnavailable("codex_containment_watch_unavailable")


def definition_probe(layout, controls):
    from . import seat_window_supply
    raise seat_window_supply.WindowRefused("window_reduction_unavailable")


def reduce_containment(inputs):
    from . import seat_window_supply
    raise seat_window_supply.WindowRefused("window_reduction_unavailable")
