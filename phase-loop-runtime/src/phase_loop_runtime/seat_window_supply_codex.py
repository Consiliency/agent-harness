"""Codex's window supplier (FIRSTSEAT amendment K-1, contract r5.2 §10.B).

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
    """§5.5's closed class for one launch result.

    A ``timeout`` (a not-ready CLI's included) is returned before the stream-completeness
    check. That is safe because ``timeout`` is never a pass class for ``measured`` or
    ``expired_copy`` (§5.5); K1-T7's not-ready completeness is the A-C1 test's own check."""
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
# SL-6.5: the I-4 rows and host paths, the scope, refresh and secret outcomes.
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
    return jailq.QualificationInput(repo=repo, commit=_head_commit(repo), layout=layout)


def _head_commit(repo) -> str:
    """The fresh repository's HEAD commit, read from its own ``.git`` (HEAD, then the loose
    branch ref the commit just wrote); no further process is started."""
    git = repo / ".git"
    head = (git / "HEAD").read_text(encoding="ascii").strip()
    if head.startswith("ref: "):
        ref = head.removeprefix("ref: ").strip()
        if not ref.startswith("refs/heads/") or ".." in ref:
            raise ValueError("stage_refused")
        head = (git / ref).read_text(encoding="ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", head) is None:
        raise ValueError("stage_refused")
    return head


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


# --------------------------------------------------------------------------------------
# I-7: Codex's bracket (§10.B), its rows ported from ``codex-unlisted-endpoint``
# (plans/evidence/seat-codex/allowlist-probes.json; pinned method input, never executed).
# The token POST is the allowlist's refused token host; the rows are that evidence's refused
# hosts and refused paths, the allowlist's own unlisted probe host, and the proxy's tunnel,
# front and direct-egress refusals re-aimed at Codex's allowed host. Nothing here probes a
# Gemini host or path.
# --------------------------------------------------------------------------------------

#: The bracket's rows, in run order after the token POST.
BRACKET_ROW_NAMES = (
    "codex_refused_hosts", "codex_refused_paths", "codex_tunnel_inner_host",
    "codex_tunnel_inner_sni_and_host", "codex_tunnel_inner_sni_only",
    "codex_fail_closed_front", "codex_direct_without_proxy",
)
_TUNNEL_SIGNATURES = frozenset({"proxy_connect_refused", "request_filter_refused",
                                "handshake_refused"})
#: The refusal signatures each row may report (FIRSTSEAT's vocabulary, ``seat_jail_qualification
#: .BRACKET_SIGNATURES``); a step reports one only on positive evidence it ran and was refused.
BRACKET_SIGNATURES = MappingProxyType({
    "codex_refused_hosts": frozenset({"proxy_connect_refused"}),
    "codex_refused_paths": frozenset({"proxy_connect_refused", "request_filter_refused"}),
    "codex_tunnel_inner_host": _TUNNEL_SIGNATURES,
    "codex_tunnel_inner_sni_and_host": _TUNNEL_SIGNATURES,
    "codex_tunnel_inner_sni_only": _TUNNEL_SIGNATURES,
    "codex_fail_closed_front": frozenset({"no_upstream_bytes"}),
    "codex_direct_without_proxy": frozenset({"resolve_refused", "connect_refused"}),
})
TOKEN_POST_STEP = "token_post"
TOKEN_POST_SIGNATURE = "proxy_connect_refused"
#: The allowed host (``codex-allowlist.json``) and one measured-and-refused host on its domain.
BRACKET_ALLOWED_HOST, BRACKET_REFUSED_HOST = MODEL_HOST, "ab.chatgpt.com"
#: ``decisions``' refused hosts (``ab.chatgpt.com``, measured and refused) and the allowlist's
#: unlisted probe host (``seat_egress_proxy._probe_rows``): each refused at ``CONNECT``.
REFUSED_HOST_TARGETS = (
    ("POST", "https://ab.chatgpt.com/otlp/v1/metrics"),
    ("GET", "https://seat-egress-unlisted.invalid/"),
)
#: ``decisions``' refused paths on the allowed host: each refused inside the tunnel.
REFUSED_PATH_TARGETS = (
    ("GET", "https://chatgpt.com/backend-api/codex/models"),
    ("GET", "https://chatgpt.com/backend-api/wham/settings/user"),
    ("POST", "https://chatgpt.com/backend-api/codex/analytics-events/events"),
)
DIRECT_TARGETS = ("https://1.1.1.1/", "https://chatgpt.com/")


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BracketRow:
    row: str
    outcome: str  # "refused" | "unavailable"
    signature: str | None


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BracketResult:
    start: object
    end: object
    post_refused: bool
    rows: tuple[BracketRow, ...]


def _curl(run, method: str, url: str, *extra: str, use_proxy: bool = True):
    from . import seat_jail_qualification as jailq
    verb = ("--request", "POST") if method == "POST" else ()
    return jailq._curl_step(run, url, *verb, *extra, use_proxy=use_proxy)


def _refusal(done) -> str | None:
    from . import seat_jail_qualification as jailq
    return jailq._curl_refusal(done)


def _token_post(run) -> str | None:
    refusal = _refusal(_curl(run, "POST", f"https://{TOKEN_HOST}{TOKEN_PATH}"))
    return TOKEN_POST_SIGNATURE if refusal == TOKEN_POST_SIGNATURE else None


def _refused_hosts(run) -> str | None:
    refusals = [_refusal(_curl(run, method, url)) for method, url in REFUSED_HOST_TARGETS]
    return ("proxy_connect_refused"
            if all(item == "proxy_connect_refused" for item in refusals) else None)


def _refused_paths(run) -> str | None:
    refusals = [_refusal(_curl(run, method, url)) for method, url in REFUSED_PATH_TARGETS]
    if not all(item in BRACKET_SIGNATURES["codex_refused_paths"] for item in refusals):
        return None
    return ("request_filter_refused" if "request_filter_refused" in refusals
            else "proxy_connect_refused")


_MODEL_URL = f"https://{MODEL_HOST}{MODEL_PATH}"
_REFUSED_MODEL_URL = f"https://{BRACKET_REFUSED_HOST}{MODEL_PATH}"
_CONNECT_TO = f"{BRACKET_REFUSED_HOST}:443:{BRACKET_ALLOWED_HOST}:443"


def _tunnel_inner_host(run) -> str | None:
    return _refusal(_curl(run, "POST", _MODEL_URL, "--header", f"Host: {BRACKET_REFUSED_HOST}"))


def _tunnel_inner_sni_and_host(run) -> str | None:
    return _refusal(_curl(run, "POST", _REFUSED_MODEL_URL, "--connect-to", _CONNECT_TO))


def _tunnel_inner_sni_only(run) -> str | None:
    return _refusal(_curl(run, "POST", _REFUSED_MODEL_URL,
                          "--header", f"Host: {BRACKET_ALLOWED_HOST}",
                          "--connect-to", _CONNECT_TO))


_FAIL_CLOSED_FRONT = r'''
import base64, os, socket, urllib.parse

proxy = urllib.parse.urlsplit(os.environ.get("HTTPS_PROXY", ""))
if (proxy.scheme != "http" or proxy.hostname != "127.0.0.1" or proxy.port is None
        or proxy.username is None or proxy.password is None):
    raise SystemExit(2)
username = urllib.parse.unquote(proxy.username)
password = urllib.parse.unquote(proxy.password)
auth = base64.b64encode(f"{username}:{password}".encode()).decode()
allowed = b"chatgpt.com"
sni = b"ab.chatgpt.com"

def attempt(record_version):
    extension = (b"\x00\x00" + (len(sni) + 5).to_bytes(2, "big")
                 + (len(sni) + 3).to_bytes(2, "big") + b"\x00"
                 + len(sni).to_bytes(2, "big") + sni)
    body = (b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x00\x02\x13\x01"
            + b"\x01\x00" + len(extension).to_bytes(2, "big") + extension)
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    record = (b"\x16\x03" + bytes([record_version])
              + len(handshake).to_bytes(2, "big") + handshake)
    sock = socket.create_connection((proxy.hostname, proxy.port), 5)
    sock.settimeout(8)
    request = (b"CONNECT " + allowed + b":443 HTTP/1.1\r\nHost: " + allowed
               + b":443\r\nProxy-Authorization: Basic " + auth.encode() + b"\r\n\r\n")
    sock.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response and len(response) < 4096:
        chunk = sock.recv(4096 - len(response))
        if not chunk:
            break
        response += chunk
    if not (response.startswith(b"HTTP/1.1 200 ") or response.startswith(b"HTTP/1.0 200 ")):
        raise SystemExit(3)
    sock.sendall(record)
    try:
        reply = sock.recv(4096)
    except OSError:
        reply = b""
    finally:
        sock.close()
    return len(reply)

print("UPSTREAM_BYTES", attempt(4), attempt(3))
'''


def _fail_closed_front(run) -> str | None:
    from . import seat_jail_qualification as jailq
    done = run(("/usr/bin/python3", "-I", "-c", _FAIL_CLOSED_FRONT),
               env=jailq.BRACKET_STEP_ENV, use_proxy=True, timeout_s=60.0)
    if (not done.timed_out and done.exit_code == 0
            and done.stdout.strip() == b"UPSTREAM_BYTES 0 0"):
        return "no_upstream_bytes"
    return None


def _direct_without_proxy(run) -> str | None:
    results = [_curl(run, "GET", target, use_proxy=False) for target in DIRECT_TARGETS]
    refusal_exits = {6, 7}  # curl's resolve and connect refusals
    if any(done.timed_out or done.exit_code not in refusal_exits for done in results):
        return None
    return ("resolve_refused" if any(done.exit_code == 6 for done in results)
            else "connect_refused")


#: The bracket's steps, in run order: the token POST, then :data:`BRACKET_ROW_NAMES`.
BRACKET_STEPS = MappingProxyType({
    TOKEN_POST_STEP: _token_post,
    "codex_refused_hosts": _refused_hosts,
    "codex_refused_paths": _refused_paths,
    "codex_tunnel_inner_host": _tunnel_inner_host,
    "codex_tunnel_inner_sni_and_host": _tunnel_inner_sni_and_host,
    "codex_tunnel_inner_sni_only": _tunnel_inner_sni_only,
    "codex_fail_closed_front": _fail_closed_front,
    "codex_direct_without_proxy": _direct_without_proxy,
})


def _bracket_step(name: str, run) -> str | None:
    step = BRACKET_STEPS.get(name)
    if step is None:
        return None
    try:
        signature = step(run)
    except Exception:  # noqa: BLE001 - a failed step is an unmade observation
        return None
    allowed = ({TOKEN_POST_SIGNATURE} if name == TOKEN_POST_STEP
               else BRACKET_SIGNATURES.get(name, frozenset()))
    return signature if isinstance(signature, str) and signature in allowed else None


def run_bracket(proxy, run) -> BracketResult:
    """The measured leg's Codex bracket. The kit calls it after the leg's acknowledged end
    fence and quiescence. It fences its own ``bracket`` window; no step runs unless that
    start fence was acknowledged. A row that did not report one of its signatures is
    ``unavailable``."""
    from . import seat_egress_proxy
    unsent = seat_egress_proxy.FenceResult(fence_id="", acknowledged=False, acked_ns=None)
    start = seat_egress_proxy.fence(proxy, "start", "bracket")
    if not start.acknowledged:
        return BracketResult(start=start, end=unsent, post_refused=False, rows=tuple(
            BracketRow(row=name, outcome="unavailable", signature=None)
            for name in BRACKET_ROW_NAMES))
    post_refused = _bracket_step(TOKEN_POST_STEP, run) == TOKEN_POST_SIGNATURE
    rows = []
    for name in BRACKET_ROW_NAMES:
        signature = _bracket_step(name, run)
        rows.append(BracketRow(row=name, outcome="refused" if signature else "unavailable",
                               signature=signature))
    end = seat_egress_proxy.fence(proxy, "end", "bracket")
    return BracketResult(start=start, end=end, post_refused=post_refused, rows=tuple(rows))


def bracket_steps():
    """Codex's own bracket, :func:`run_bracket`."""
    return run_bracket


# --------------------------------------------------------------------------------------
# I-5 and I-13: Codex's containment watch, definition probe and reducer.
#
# They are Codex's own and self-contained: they call no ``seat_jail_qualification`` reducer,
# definition or binding helper. The watch reuses FIRSTSEAT's inotify mechanics (``SeatWatch``)
# over Codex's host paths. The value types the kit hands over (``LaunchBinding``,
# ``WatchObservation``, ``PlantLayout``) are vendor-neutral and are read, not re-exported.
#
# What a non-Gemini leg does not give the reducer, and what follows:
# * no lookup trace: no lookup is counted, and a surface is defined only by a row a valid
#   control opened;
# * no post-launch row scan: a row's change is the watch's change event, and the home row
#   has no digest baseline, so a change there leaves every surface ``unavailable``;
# * no issuer: the scope is ``scope_problem`` on the seat's copy (§10.B).
# --------------------------------------------------------------------------------------

SURFACES = ("project_settings", "hooks", "mcp_servers", "provider_overrides")
CONTAINMENT_FIELDS = ("credential_scope", "refresh_detection", *SURFACES)
SCOPE_EXCESS = "codex_seat_token_scope_excess"
REFRESHED = "codex_seat_token_refreshed_in_jail"
HOME_ROW_ID = f"{HOME_ROW[0]}:{HOME_ROW[1]}"
_CONTROL_KINDS = frozenset({"tree_control", "runtime_control", "credentialed_tree_control",
                            "credentialed_runtime_control"})
_COUNTED_ADMISSION_CLASSES = frozenset({"release_qualified", "locally_qualified"})
#: The kit binds ``str(seat.admission_class)``. A Codex seat with no admission class (the
#: pinned state today) therefore binds ``"None"``; that string, like an empty one, means
#: "no class" and is never compared as a class value.
_NO_ADMISSION_CLASS = frozenset({"", "None"})


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ContextBinding:
    context_id: str
    account_label: str
    dependency_subject_sha256: str | None
    dependency_projection_sha256: str | None


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ContainmentInputs:
    context: ContextBinding
    layout: object
    help: object | None
    plugin_validation: object | None
    controls: tuple
    measured: object | None
    expired_copy: object | None
    board: object | None


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class VoidedControl:
    kind: str
    reason: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class DefinitionResult:
    defined_rows: tuple[str, ...]
    defined_surfaces: tuple[str, ...]
    home_row_baseline: str  # "write_recorded" | "no_write_final" | "absent"
    credentialed_control_required: bool
    counted_lookups: Mapping[str, int]
    uncounted_home_lookups: Mapping[str, int]
    voided: tuple[VoidedControl, ...]


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class OwnerSummary:
    schema: str
    context_id: str
    outcomes: Mapping[str, str]
    unavailable_reasons: Mapping[str, tuple[str, ...]]
    undefined_surfaces: tuple[str, ...]
    plugin_validation: str
    home_row_baseline: str
    counted_lookups: Mapping[str, int]
    uncounted_home_lookups: Mapping[str, int]
    voided_controls: tuple[VoidedControl, ...]
    expired_copy_control: str
    private_route: bool


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ContainmentReduction:
    containment: Mapping[str, str]
    checks: Mapping[str, bool]
    observation_sha256: str
    binding: Mapping[str, str | None]
    admitted: bool
    private: Mapping[str, object] = dataclasses.field(repr=False)
    owner_summary: OwnerSummary


# --- I-5: the watch -------------------------------------------------------------------

_WATCH_KINDS = frozenset({*LAUNCH_KINDS, "board"})
_WATCH_CLASS = None


def _pre_row_digests(layout, paths) -> Mapping[str, str | None]:
    from . import seat_jail_qualification as jailq, seat_uid
    values: dict[str, str | None] = {}
    for row in layout.rows:
        if row.location == "tree":
            continue
        relative = jailq._row_parts(row.row_id)[1]
        path, _boundary = _host_target(paths, row.location, relative)
        values[row.row_id] = (seat_uid.tree_manifest_digest(path) if relative.endswith("/")
                              else jailq._regular_sha256(path))
    return MappingProxyType(values)


def _watch_class():
    """``CodexSeatWatch``: FIRSTSEAT's parent-held inotify handle, armed on Codex's paths
    (the tree's rows and sentinels, ``workdir``, ``home`` and ``provider_config``, and the
    delivered ``.codex/auth.json``). Built on first use, so loading the supplier imports
    nothing more."""
    global _WATCH_CLASS
    if _WATCH_CLASS is not None:
        return _WATCH_CLASS
    import os
    import time as _time
    from . import seat_jail_qualification as jailq, seat_uid

    class CodexSeatWatch(jailq.SeatWatch):
        def __init__(self, layout, paths, *, kind):  # noqa: D107 - replaces SeatWatch's paths
            import ctypes
            self.armed_ns = _time.monotonic_ns()
            self._layout, self._paths, self._kind = layout, paths, kind
            self._fd, self._closed, self._overflow = -1, False, False
            self._opened, self._changed = set(), set()
            self._row_ancestor_created = False
            self._credential_events = 0
            self._sentinels, self._read_marker = set(), False
            self._file_watches, self._directory_watches, self._credential_watches = {}, {}, {}
            try:
                self._pre_rows = _pre_row_digests(layout, paths)
                manifest = seat_uid.tree_manifest_digest(paths.tree)
                if manifest is None:
                    raise jailq.WatchUnavailable("tree manifest is unavailable before launch")
                self._pre_tree = manifest
                libc = ctypes.CDLL(None, use_errno=True)
                libc.inotify_init1.argtypes = [ctypes.c_int]
                libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p,
                                                   ctypes.c_uint32]
                self._libc = libc
                self._fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
                if self._fd < 0:
                    raise OSError(ctypes.get_errno(), "inotify_init1")
                for row in layout.rows:
                    relative = jailq._row_parts(row.row_id)[1]
                    plant, _boundary = _host_target(paths, row.location, relative)
                    for member in jailq._plant_members(plant):
                        self._add_file(member, row.row_id, "row")
                    if not relative.endswith("/") and row.role in ("hooks", "mcp_servers"):
                        executable = plant.with_name(plant.name + ".inert")
                        if executable.is_file():
                            self._add_file(executable, row.row_id, "row")
                self._add_file(paths.tree / jailq.WATCH_OPEN_SENTINEL,
                               jailq.WATCH_OPEN_SENTINEL, "open")
                self._add_file(paths.tree / jailq.WATCH_EXEC_SENTINEL,
                               jailq.WATCH_EXEC_SENTINEL, "exec")
                self._add_file(paths.tree / jailq.WINDOW_READ_PATH, jailq.WINDOW_READ_PATH,
                               "read")
                for location, root in (("workdir", paths.seat_home / "workspace"),
                                       ("home", paths.seat_home),
                                       ("provider_config", paths.provider_config)):
                    self._add_directories(location, root)
                if paths.delivered_credential is not None:
                    self._add_credential(paths.delivered_credential)
            except (OSError, ValueError, jailq.WatchUnavailable, AttributeError,
                    jailq.PlantLayoutRefused, TypeError):
                self._close_fd()
                raise jailq.WatchUnavailable("codex watch could not be armed") from None

        def _rows_for_change(self, location, relative):
            changed: set[str] = set()
            candidate = relative.rstrip("/")
            for row in self._layout.rows:
                if row.location != location:
                    continue
                row_path = jailq._row_parts(row.row_id)[1].rstrip("/")
                if (candidate == row_path or candidate.startswith(row_path + "/")
                        or row_path.startswith(candidate + "/")):
                    changed.add(row.row_id)
            return changed

    _WATCH_CLASS = CodexSeatWatch
    return _WATCH_CLASS


def arm_watch(layout, paths, *, kind):
    """I-5 on Codex's paths. The layout must be Codex's own; anything else, or a location
    that cannot be watched, raises ``WatchUnavailable``."""
    from . import seat_jail_qualification as jailq
    if kind not in _WATCH_KINDS:
        raise ValueError("unknown launch kind")
    if not _layout_complete(layout) or not isinstance(paths, CodexHostPathMap):
        raise jailq.WatchUnavailable("codex watch input is not codex's")
    return _watch_class()(layout, paths, kind=kind)


# --- reduction helpers (Codex's own) --------------------------------------------------

def _sha256_text(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _is_digest(value) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _all_events(stream) -> tuple:
    if stream is None:
        return ()
    return (*getattr(stream, "outside_events", ()),
            *(event for window in getattr(stream, "windows", ()) for event in window.events))


def _window(stream, label: str):
    values = [window for window in getattr(stream, "windows", ()) if window.label == label]
    return values[0] if len(values) == 1 else None


def _stream_complete(stream, *, labels: tuple[str, ...], inference: bool) -> bool:
    if (stream is None or not stream.final or stream.protocol_error or stream.outside_events
            or tuple(window.label for window in stream.windows) != labels
            or any(not window.start_acked or not window.end_acked
                   for window in stream.windows)):
        return False
    return not inference or any(_model_request(event) and event.decision == "allow"
                                for event in _window(stream, "leg").events)


def _token_events(result) -> tuple:
    return tuple(event for event in _all_events(getattr(result, "stream", None))
                 if token_endpoint(event))


def _allowed_token_request(result) -> bool:
    """§10.B's second refresh arm: an allowed token-endpoint request, in any window."""
    return any(event.decision == "allow" for event in _token_events(result))


def _scan_value(result, name: str) -> str | None:
    scan = getattr(result, "scan", None)
    value = scan.get(name) if isinstance(scan, Mapping) else None
    return value if isinstance(value, str) else None


def _credential_event(result) -> bool:
    """A change at the delivered credential: the watch saw it written, or the pre-teardown
    read found the tokens changed (or the copy removed)."""
    watch = getattr(result, "watch", None)
    return bool((watch is not None and watch.credential_path_events)
                or _scan_value(result, "refresh") == REFRESHED)


def _watch_complete(result, *, measured: bool) -> bool:
    watch = getattr(result, "watch", None)
    first = getattr(result, "first_jailed_launch_ns", None)
    return bool(watch is not None and first is not None and watch.armed_ns <= first
                and watch.sentinel_observed and not watch.overflow
                and (watch.read_marker_opened or not measured)
                and watch.drained_after_quiescence and result.quiescent
                and not watch.row_ancestor_created)


def _control_void_reasons(result) -> tuple[str, ...]:
    reasons: list[str] = []
    if result.error is not None or result.timed_out or result.status == "NONE":
        reasons.append("launch_error")
    if result.tool_steps != 0:
        reasons.append("tool_step")
    if result.subagent_steps != 0:
        reasons.append("subagent_step")
    if _token_events(result):
        reasons.append("token_endpoint_event")
    if _credential_event(result):
        reasons.append("credential_event")
    if not _watch_complete(result, measured=False):
        reasons.append("incomplete_watch")
    if result.kind.startswith("credentialed_") and (
            _scan_value(result, "scope") is None or _scan_value(result, "refresh") is None):
        reasons.append("incomplete_watch")
    return tuple(dict.fromkeys(reasons))


def _row_table(layout) -> Mapping[str, object]:
    return {row.row_id: row for row in layout.rows}


def definition_probe(layout, controls) -> DefinitionResult:
    """Codex's pure section 7 reduction over the control launches completed so far. With no
    lookup trace, a surface is defined only by a row that a valid control's watch saw
    opened; no lookup is counted."""
    defined: set[str] = set()
    voided: list[VoidedControl] = []
    present_credentialed = valid_credentialed_tree = home_written = False
    for control in controls:
        if control.kind not in _CONTROL_KINDS:
            continue
        present_credentialed |= control.kind.startswith("credentialed_")
        reasons = _control_void_reasons(control)
        voided.extend(VoidedControl(kind=control.kind, reason=reason) for reason in reasons)
        if reasons:
            continue
        valid_credentialed_tree |= control.kind == "credentialed_tree_control"
        defined.update(control.watch.opened_rows)
        home_written |= HOME_ROW_ID in control.watch.changed_rows
    table = _row_table(layout)
    defined = {row_id for row_id in defined if row_id in table}
    surfaces = tuple(surface for surface in SURFACES
                     if any(table[row_id].role == surface for row_id in defined))
    home_baseline = ("write_recorded" if home_written
                     else "no_write_final" if valid_credentialed_tree else "absent")
    required = (not present_credentialed
                and (set(surfaces) != set(SURFACES) or home_baseline == "absent"))
    return DefinitionResult(
        defined_rows=tuple(row.row_id for row in layout.rows if row.row_id in defined),
        defined_surfaces=surfaces, home_row_baseline=home_baseline,
        credentialed_control_required=required,
        counted_lookups=MappingProxyType({}), uncounted_home_lookups=MappingProxyType({}),
        voided=tuple(voided))


def _runtime_or_home_change(result, definitions: DefinitionResult) -> bool:
    """Section 8: ``not_loaded`` needs no change at a defined workdir, home or
    provider_config row, and none at the home row."""
    from . import seat_jail_qualification as jailq
    watch = getattr(result, "watch", None)
    defined = set(definitions.defined_rows)
    for row_id in (watch.changed_rows if watch is not None else ()):
        if row_id == HOME_ROW_ID:
            return True
        location = jailq._row_parts(row_id)[0]
        if location in ("workdir", "home", "provider_config") and row_id in defined:
            return True
    return False


def _canary_surfaces(layout, stream) -> set[str]:
    hosts = {host: surface for surface, values in layout.canary_hosts.items()
             for host in values}
    return {hosts[event.host] for event in _all_events(stream) if event.host in hosts}


def _positive_surfaces(layout, result) -> set[str]:
    if result is None:
        return set()
    table = _row_table(layout)
    watch = result.watch
    rows = (*watch.opened_rows, *watch.changed_rows) if watch is not None else ()
    return ({table[row_id].role for row_id in rows if row_id in table}
            | _canary_surfaces(layout, result.stream))


def _positive_board_surfaces(layout, board) -> set[str]:
    if board is None:
        return set()
    table = _row_table(layout)
    watch = board.watch
    return ({table[row_id].role for row_id in (watch.opened_rows if watch else ())
             if row_id in table} | _canary_surfaces(layout, board.stream))


def _bracket_valid(result) -> bool:
    """Codex's bracket ran whole: both fences acknowledged, the token POST refused, every
    row refused with one of its signatures, and the bracket window's only token-endpoint
    event the token POST's denial."""
    bracket = getattr(result, "bracket", None)
    window = _window(getattr(result, "stream", None), "bracket")
    if (not isinstance(bracket, BracketResult) or window is None
            or not getattr(bracket.start, "acknowledged", False)
            or not getattr(bracket.end, "acknowledged", False) or not bracket.post_refused
            or tuple(row.row for row in bracket.rows) != BRACKET_ROW_NAMES
            or any(row.outcome != "refused" or row.signature not in BRACKET_SIGNATURES[row.row]
                   for row in bracket.rows)):
        return False
    token = [event for event in window.events if token_endpoint(event)]
    return len(token) == 1 and token[0].decision == "deny"


def _allowlist_role(kind: str) -> str:
    """The proxy rule set a launch of ``kind`` must bind: the empty set (``refuse_all``) for
    the ``none`` kinds, the production ``codex`` allowlist for every credentialed kind.

    The ``expired_copy`` line is the seam the OI-1 fence edits: today the expired leg runs the
    production allowlist (§10.B), so it binds the production digest."""
    if kind == "expired_copy":
        return "production"
    return "refuse_all" if kind in _NONE_KINDS else "production"


def _expected_allowlists() -> dict[str, str | None]:
    """The digests a Codex launch's proxy binds (``SeatEgressProxy.allowlist_sha256``): the
    empty rule set, and the packaged production ``codex`` allowlist's rules."""
    from . import seat_egress_proxy
    try:
        production = seat_egress_proxy._digest(
            list(seat_egress_proxy.allowlist_ref(CODEX_WINDOW_DATA.leg).request_set))
    except Exception:  # noqa: BLE001 - an unreadable allowlist binds nothing
        production = None
    return {"refuse_all": seat_egress_proxy._digest([]), "production": production}


def _expected_jail_profile() -> str | None:
    from . import seat_jail
    try:
        return seat_jail.jail_profile_digest(CODEX_WINDOW_DATA.leg)
    except Exception:  # noqa: BLE001 - no canonical profile binds nothing
        return None


def _input_digests() -> tuple[str, str, str]:
    """The kit's control, measured and board inputs (the texts the kit sends a Codex leg)."""
    from . import panel_invoker as panel
    return (_sha256_text(panel._WINDOW_CONTROL_INPUT), _sha256_text(panel._WINDOW_MEASURED_INPUT),
            panel.window_board_input_sha256())


def _identity(binding) -> tuple:
    return (binding.image_sha256, binding.admission_class, binding.stage_manifest_sha256,
            binding.jail_profile_sha256)


def _launch_valid(result, identity, *, inputs: tuple[str, str, str],
                  allowlists: Mapping[str, str | None]) -> bool:
    binding = getattr(result, "binding", None)
    if binding is None or not all(_is_digest(value) for value in (
            binding.image_sha256, binding.stage_manifest_sha256, binding.argv_sha256,
            binding.jail_profile_sha256, binding.allowlist_sha256)):
        return False
    if not isinstance(binding.admission_class, str) or identity is None \
            or _identity(binding) != identity:
        return False
    if result.kind not in LAUNCH_KINDS:
        return False
    expected = allowlists.get(_allowlist_role(result.kind))
    if expected is None or binding.allowlist_sha256 != expected:
        return False
    if result.kind == "help":
        return binding.input_sha256 is None and _is_digest(getattr(result, "help_sha256", None))
    return binding.input_sha256 == (inputs[0] if result.kind in _CONTROL_KINDS else inputs[1])


def _admission_class(binding) -> str | None:
    value = getattr(binding, "admission_class", None)
    return None if not isinstance(value, str) or value in _NO_ADMISSION_CLASS else value


def _expired_copy_state(measured, expired) -> str:
    """``pass`` when the measured leg is ``completed`` and the expired leg
    ``refused_intended`` (§5.5) on complete watches, scans and streams; ``fail`` on a
    credential change or an allowed token-endpoint request; else ``unavailable``."""
    if measured is None or expired is None:
        return "unavailable"
    if (_credential_event(measured) or _credential_event(expired)
            or _allowed_token_request(measured) or _allowed_token_request(expired)):
        return "fail"
    if (not _watch_complete(measured, measured=True)
            or not _watch_complete(expired, measured=False)
            or measured.bridge_exited is not True or expired.bridge_exited is not True
            or _scan_value(measured, "refresh") != "pass"
            or _scan_value(expired, "refresh") != "pass"
            or not _stream_complete(measured.stream, labels=("leg", "bracket"), inference=True)
            or not _stream_complete(expired.stream, labels=("leg",), inference=False)):
        return "unavailable"
    if terminal(measured) == "completed" and terminal(expired) == "refused_intended":
        return "pass"
    return "unavailable"


def _plain(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name))
                for item in dataclasses.fields(value) if item.name != "content"}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, bytes):
        return "<bytes>"
    if value is None or type(value) in (str, int, float, bool):
        return value
    return str(value)


def _implementation_digests() -> dict[str, str]:
    """``watch_sha256``, ``proxy_sha256`` and ``validator_sha256``: the bytes that decide each.
    The watch is this module's arming over FIRSTSEAT's inotify mechanics; the validator is
    this module and the credential reads it decides on; the proxy is FIRSTSEAT's formula."""
    import hashlib
    from pathlib import Path
    from . import seat_codex_credential, seat_egress_proxy, seat_jail_qualification
    own = Path(__file__).read_bytes()
    mechanics = Path(seat_jail_qualification.__file__).read_bytes()
    credential = Path(seat_codex_credential.__file__).read_bytes()
    proxy = (Path(seat_egress_proxy.__file__).read_bytes() + b"\0"
             + seat_egress_proxy._data_path("proxy.mjs").read_bytes())
    return {
        "watch_sha256": hashlib.sha256(b"codex-seat-watch.v1\0" + own + b"\0"
                                       + mechanics).hexdigest(),
        "proxy_sha256": hashlib.sha256(proxy).hexdigest(),
        "validator_sha256": hashlib.sha256(b"codex-containment-validator.v1\0" + own + b"\0"
                                           + credential).hexdigest(),
    }


def _add_reason(reasons: dict[str, list[str]], name: str, reason: str) -> None:
    if reason not in reasons[name]:
        reasons[name].append(reason)


# --- I-13: the reducer ----------------------------------------------------------------

def reduce_containment(inputs: ContainmentInputs) -> ContainmentReduction:
    """Purely reduce one Codex context's frozen observations to I-13's closed reduction;
    absent assurance stays ``unavailable``.

    * Bindings: every launch shares one image, admission class, stage and jail profile (the
      canonical Codex profile); one control argv and one production argv, which differ; each
      launch binds its kind's input and its rule set's digest: the empty set for the ``none``
      kinds, the packaged production ``codex`` allowlist for the credentialed kinds
      (:func:`_allowlist_role`, the OI-1 seam). Anything else is ``binding_mismatch``.
    * Admission: ``release_qualified``, ``locally_qualified``, or ``executable_dependency``
      with the context's dependency subject equal to the image. ``"None"`` is no class.
    * Scope: ``scope_problem`` on the seat's copy (§10.B), with the bracket whole.
    * Refresh: ``codex_seat_token_refreshed_in_jail`` on a credential change (the tokens
      changed, the copy removed, or the watch saw it written) or an allowed token-endpoint
      request (§10.B); ``pass`` needs the expired-copy control's ``pass``.
    * Surfaces: ``loaded`` on an opened or changed row or a canary request; ``not_loaded``
      only for a defined surface on complete measured observations with no change at a
      defined runtime row or the home row."""
    if not isinstance(inputs, ContainmentInputs):
        raise TypeError("inputs must be Codex's ContainmentInputs")
    layout = inputs.layout
    allowlists = _expected_allowlists()
    input_digests = _input_digests()
    control_input, measured_input, board_input = input_digests
    observed_measured, observed_expired, observed_board = (
        inputs.measured, inputs.expired_copy, inputs.board)
    launches = tuple(item for item in (inputs.help, *inputs.controls, inputs.measured,
                                       inputs.expired_copy) if item is not None)
    reference = next((item.binding for item in launches if item.binding is not None), None)
    identity = _identity(reference) if reference is not None else None
    valid = {id(item): _launch_valid(item, identity, inputs=input_digests,
                                     allowlists=allowlists) for item in launches}
    binding_mismatch = (not all(valid.values()) or not _layout_complete(layout)
                        or inputs.help is None or inputs.plugin_validation is not None
                        or identity is None or identity[3] != _expected_jail_profile())
    valid_controls = tuple(item for item in inputs.controls if valid.get(id(item), False))
    measured = inputs.measured if inputs.measured is not None and valid[id(inputs.measured)] \
        else None
    expired = (inputs.expired_copy if inputs.expired_copy is not None
               and valid[id(inputs.expired_copy)] else None)
    control_argvs = {item.binding.argv_sha256 for item in valid_controls
                     if item.kind in _TREE_KINDS}
    production_argvs = {item.binding.argv_sha256 for item in (*valid_controls, measured, expired)
                        if item is not None and item.kind not in _TREE_KINDS}
    if (len(control_argvs) != 1 or len(production_argvs) != 1
            or control_argvs == production_argvs):
        binding_mismatch = True
    definitions = definition_probe(layout, valid_controls)
    board = observed_board
    if board is not None and (
            board.binding is None or identity is None or _identity(board.binding) != identity
            or board.input_sha256 != board_input
            or board.binding.allowlist_sha256 != allowlists["production"]):
        board = None
        binding_mismatch = True

    admission_class = _admission_class(reference)
    admitted = bool(admission_class is not None and (
        admission_class in _COUNTED_ADMISSION_CLASSES
        or (admission_class == "executable_dependency"
            and inputs.context.dependency_subject_sha256 == reference.image_sha256)))
    positives = _positive_surfaces(layout, measured) | _positive_board_surfaces(layout, board)
    observed_positives = (_positive_surfaces(layout, observed_measured)
                          | _positive_board_surfaces(layout, observed_board))
    outcomes = dict.fromkeys(CONTAINMENT_FIELDS, "unavailable")
    reasons: dict[str, list[str]] = {name: [] for name in CONTAINMENT_FIELDS}
    measured_watch_complete = measured is not None and _watch_complete(measured, measured=True)
    measured_stream_complete = measured is not None and _stream_complete(
        measured.stream, labels=("leg", "bracket"), inference=True)

    for surface in SURFACES:
        if surface in positives:
            outcomes[surface] = "loaded"
        elif not admitted:
            _add_reason(reasons, surface, "not_admitted")
        elif measured is None:
            _add_reason(reasons, surface,
                        "binding_mismatch" if binding_mismatch else "missing_input")
        elif measured.error is not None:
            _add_reason(reasons, surface, "launch_error")
        elif measured.timed_out:
            _add_reason(reasons, surface, "timed_out")
        elif surface not in definitions.defined_surfaces:
            _add_reason(reasons, surface, "undefined_surface")
        elif not measured_watch_complete:
            _add_reason(reasons, surface, "incomplete_watch")
        elif not measured_stream_complete:
            _add_reason(reasons, surface, "incomplete_stream")
        elif not _runtime_or_home_change(measured, definitions):
            outcomes[surface] = "not_loaded"

    scope = _scan_value(measured, "scope") if measured is not None else None
    if scope == SCOPE_EXCESS:
        outcomes["credential_scope"] = SCOPE_EXCESS
    elif not admitted:
        _add_reason(reasons, "credential_scope", "not_admitted")
    elif measured is None or scope is None:
        _add_reason(reasons, "credential_scope", "missing_input")
    elif scope != "pass":
        _add_reason(reasons, "credential_scope", "incomplete_scan")
    elif not measured_stream_complete:
        _add_reason(reasons, "credential_scope", "incomplete_stream")
    elif measured.bracket is None:
        _add_reason(reasons, "credential_scope", "bracket_void")
    elif any(row.outcome != "refused" for row in getattr(measured.bracket, "rows", ())):
        _add_reason(reasons, "credential_scope", "bracket_row_unavailable")
    elif not _bracket_valid(measured):
        _add_reason(reasons, "credential_scope", "bracket_void")
    else:
        outcomes["credential_scope"] = "pass"

    expired_state = _expired_copy_state(measured, expired)
    refresh_positive = any(item is not None and (_credential_event(item)
                                                 or _allowed_token_request(item))
                           for item in (measured, expired))
    if refresh_positive:
        outcomes["refresh_detection"] = REFRESHED
    elif not admitted:
        _add_reason(reasons, "refresh_detection", "not_admitted")
    elif measured is None or expired is None:
        _add_reason(reasons, "refresh_detection", "missing_input")
    elif not measured_watch_complete:
        _add_reason(reasons, "refresh_detection", "incomplete_watch")
    elif _scan_value(measured, "refresh") != "pass" or _scan_value(expired, "refresh") != "pass":
        _add_reason(reasons, "refresh_detection", "incomplete_scan")
    elif not measured_stream_complete:
        _add_reason(reasons, "refresh_detection", "incomplete_stream")
    elif not _bracket_valid(measured):
        _add_reason(reasons, "refresh_detection", "bracket_void")
    elif expired_state != "pass":
        _add_reason(reasons, "refresh_detection", "expired_copy_unavailable")
    else:
        outcomes["refresh_detection"] = "pass"

    positive_values = ("loaded", SCOPE_EXCESS, REFRESHED)
    if binding_mismatch:
        for name in CONTAINMENT_FIELDS:
            if outcomes[name] not in positive_values:
                outcomes[name] = "unavailable"
                _add_reason(reasons, name, "binding_mismatch")
    owner_outcomes = dict(outcomes)
    observed_refresh = any(item is not None and (_credential_event(item)
                                                 or _allowed_token_request(item))
                           for item in (observed_measured, observed_expired))
    observed_excess = (observed_measured is not None
                       and _scan_value(observed_measured, "scope") == SCOPE_EXCESS)
    for surface in observed_positives:
        owner_outcomes[surface] = "loaded"
    if observed_excess:
        owner_outcomes["credential_scope"] = SCOPE_EXCESS
    if observed_refresh:
        owner_outcomes["refresh_detection"] = REFRESHED
    if not admitted:
        outcomes = dict.fromkeys(CONTAINMENT_FIELDS, "unavailable")

    def _first(items, role=None, tree=None):
        for item in items:
            if item is None or item.binding is None:
                continue
            if role is not None and _allowlist_role(item.kind) != role:
                continue
            if tree is not None and (item.kind in _TREE_KINDS) != tree:
                continue
            return item.binding
        return None

    control_binding = _first(valid_controls, tree=True)
    production_binding = _first((*valid_controls, measured, expired), tree=False)
    production_allowlist = _first((measured, expired, *valid_controls), role="production")
    refuse_allowlist = _first((inputs.help, *valid_controls), role="refuse_all")
    implementation = _implementation_digests()
    binding_values: dict[str, str | None] = {
        "image_sha256": reference.image_sha256 if reference else None,
        "admission_class": reference.admission_class if reference else None,
        "help_sha256": getattr(inputs.help, "help_sha256", None),
        "stage_manifest_sha256": reference.stage_manifest_sha256 if reference else None,
        "plant_layout_sha256": getattr(layout, "layout_sha256", None),
        "contract_sha256": K1_CONTRACT_SHA256,
        "control_argv_sha256": control_binding.argv_sha256 if control_binding else None,
        "production_argv_sha256": production_binding.argv_sha256 if production_binding else None,
        "control_input_sha256": control_input,
        "measured_input_sha256": measured_input,
        "board_input_sha256": board_input,
        "jail_profile_sha256": reference.jail_profile_sha256 if reference else None,
        "production_allowlist_sha256": (production_allowlist.allowlist_sha256
                                        if production_allowlist else None),
        "refuse_all_allowlist_sha256": (refuse_allowlist.allowlist_sha256
                                        if refuse_allowlist else None),
        "watch_sha256": implementation["watch_sha256"],
        "proxy_sha256": implementation["proxy_sha256"],
        "validator_sha256": implementation["validator_sha256"],
        "dependency_subject_sha256": inputs.context.dependency_subject_sha256,
        "dependency_projection_sha256": inputs.context.dependency_projection_sha256,
        "context_id": inputs.context.context_id,
        "account_label": inputs.context.account_label,
    }

    reason_values = {name: tuple(reasons[name]) for name in CONTAINMENT_FIELDS}
    measured_watch = observed_measured.watch if observed_measured is not None else None
    board_watch = observed_board.watch if observed_board is not None else None
    delivered = getattr(observed_measured, "delivered_copy_sha256", None)
    private = {
        "rows": {
            "defined": definitions.defined_rows,
            "measured_opened": measured_watch.opened_rows if measured_watch else (),
            "measured_changed": measured_watch.changed_rows if measured_watch else (),
            "board_opened": board_watch.opened_rows if board_watch else (),
        },
        "canaries": tuple(
            event for event in (*_all_events(getattr(observed_measured, "stream", None)),
                                *_all_events(getattr(observed_board, "stream", None)))
            if any(event.host in values for values in layout.canary_hosts.values())),
        "token_endpoint_events": {"measured": _token_events(observed_measured),
                                  "expired_copy": _token_events(observed_expired)},
        "credential_events": {
            "measured": bool(observed_measured and _credential_event(observed_measured)),
            "expired_copy": bool(observed_expired and _credential_event(observed_expired)),
        },
        "lookups": {item.kind: () for item in inputs.controls},
        "home_row": {"baseline": None, "measured": None},
        "manifest_differences": False,
        "delivered_copy_sha256": delivered if _is_digest(delivered) else None,
        "bracket": getattr(observed_measured, "bracket", None),
        "issuer": None,
        "unavailable_reasons": reason_values,
    }
    private_plain = _plain(private)
    help_lists = getattr(inputs.help, "help_lists_plugin", None)
    plugin_state = "not_listed" if help_lists is False else "not_run"
    private_route = bool(observed_positives or observed_refresh or observed_excess) or any(
        value in positive_values for value in outcomes.values())
    owner = OwnerSummary(
        schema="seat_window_owner_summary.v1", context_id=inputs.context.context_id,
        outcomes=MappingProxyType(owner_outcomes),
        unavailable_reasons=MappingProxyType(reason_values),
        undefined_surfaces=tuple(surface for surface in SURFACES
                                 if surface not in definitions.defined_surfaces),
        plugin_validation=plugin_state, home_row_baseline=definitions.home_row_baseline,
        counted_lookups=definitions.counted_lookups,
        uncounted_home_lookups=definitions.uncounted_home_lookups,
        voided_controls=definitions.voided, expired_copy_control=expired_state,
        private_route=private_route)
    return ContainmentReduction(
        containment=MappingProxyType(dict(outcomes)),
        checks=MappingProxyType({name: outcomes[name] in ("not_loaded", "pass")
                                 for name in CONTAINMENT_FIELDS}),
        observation_sha256=_digest(private_plain),
        binding=MappingProxyType(binding_values),
        admitted=admitted,
        private=MappingProxyType(private_plain),
        owner_summary=owner,
    )
