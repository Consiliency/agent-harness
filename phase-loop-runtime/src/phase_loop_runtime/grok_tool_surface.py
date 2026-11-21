"""The frozen basis of the grok tool probe.

No installed grok build has ``--list-tools`` (0.1.220 through 1.0.89), so the probe's
listing path never runs and every grok route stays ``grok_tool_surface_unverified``. This
module gives the probe a second basis: a tool surface measured once per grok binary digest
and route argv digest, valid only inside one enforced launch context.

The rules are frozen in ``plans/artifacts/grok-tool-surface-contract-v1.md`` ("the
contract"); each section below names the one it implements.

- Records (§3.1, §3.2): the shipped catalog ``data/grok_tool_surfaces.json`` and the
  host-local measurement record, both strict and fail-closed: any refusal is "no record".
- Resolution (§3.2, §4.1): a revoked digest has no record; a catalog route wins; the
  host-local route is used only when the catalog has none for the key.
- The seat config (erratum 8): the pinned ``.grok/config.toml`` a grok seat's home holds
  under the ``grok-review`` proxy, as an immutable read-only mount of a sealed memfd; the
  fixed inputs that must stay absent; and the forms eligible at use.
- The launch context ``grok_seat_context.v1`` (§4.4): its digest, and the final check that
  marks a composed profile. Nothing in this lane calls that check, so no profile is ever
  marked and a frozen-basis receipt never admits a launch: lane L2c wires the board review
  leg. The digest also needs the ``grok-review`` egress allow-list, which lane L2a ships;
  until then it cannot be computed and no record is consumable at all.
- The measurement (§5, lane L2b): ``seat-window measure-tools``. One budgeted launch per
  route through the seat's own composition under a measurement admission, a durable grant
  ledger, immutable result records, and ``--aggregate`` as the only writer of the
  host-local record. It runs only under an owner grant (contract §5.10).

A record states what a build offered on one measured request. It never states "passed":
admission is still ``panel_invoker._grok_tools_admitted`` on the form's own argv.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import errno
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Mapping

CATALOG_SCHEMA = "grok_tool_surface_catalog.v1"
CATALOG_NAME = "grok_tool_surfaces.json"
CATALOG_MAX_BYTES = 256 * 1024
HOST_RECORD_SCHEMA = "grok_tool_surface_measurement.v1"
HOST_RECORD_MAX_BYTES = 16384
GROK_SEAT_CONTEXT = "grok_seat_context.v1"
#: The receipt fields a frozen-basis ``tool_probe.v1`` receipt carries (§4.2).
RECEIPT_FIELDS = ("surface_digest", "surface_source", "context", "context_digest")
SURFACE_SOURCES = ("catalog", "host_local")

_HEX64 = re.compile(r"[0-9a-f]{64}")
_TOOL = re.compile(r"[A-Za-z0-9_.-]{1,96}")
_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")
_SURFACE_KEYS = frozenset({
    "binary_sha256", "version", "version_sha256", "help_sha256", "model", "effort",
    "context", "context_digest", "measured_at", "routes"})
_ROUTE_KEYS = frozenset({"route", "argv_digest", "tools", "definitions_sha256"})

# --------------------------------------------------------------- the launch context (§4.4)

PRIVATE_HOME = "/home/phase-loop-seat"
#: What ``panel_invoker.seat_profile`` projects into a grok seat's fresh private home.
PROJECTED_PATHS = (".grok/agent_id", ".grok/auth.json")
#: The egress proxy projection of §5.2 (the proxy address and the seat egress CA), as lane
#: L2a's offline confirmation named them: ``panel_invoker._SEAT_EGRESS_CA_RELATIVE``, a
#: read-only file in the private home, and ``seat_egress_proxy.SEAT_PROXY_ENV`` and
#: ``SEAT_CA_ENV``. A test holds the three equal.
PROXY_PROJECTED_PATHS: tuple[str, ...] = (".phase-loop-seat-egress-ca.pem",)
PROXY_ENVIRONMENT: tuple[str, ...] = ("HTTPS_PROXY", "SSL_CERT_FILE")
#: Where a measurement binds its scratch sessions directory (§5.1): the one host-backed path
#: a measurement's private home may hold. No other launch may carry it.
SESSIONS_RELATIVE = ".grok/sessions"
#: The child environment ``seat_profile`` composes for grok, and nothing else.
ENVIRONMENT = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "NO_COLOR", "PATH", "TERM",
               "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME")
FORBIDDEN_ENVIRONMENT_PREFIXES = ("GROK_", "XAI_")
MANAGED_CONFIG_PATHS = ("/etc/grok/managed_config.toml", "/etc/grok/requirements.toml")
#: Claude Code's managed settings, which grok 1.0.89 also reads (permission rules, a default
#: mode, MCP and hook policy). The seat's view does not bind them; the final check proves they
#: stay out of the child's view, whatever the host holds.
CHILD_ABSENT_POLICY_PATHS = ("/etc/claude-code/managed-settings.json",)
#: The project paths grok 1.0.89 discovers that can add or reconfigure tools: plugins,
#: skills, agents, hooks, MCP servers and settings. Derived offline from the documentation
#: bundled in the 1.0.89 binary; the derivation is recorded in
#: ``tests/test_grok_tool_surface.py`` (``test_the_pinned_discovery_set``). Rules files
#: (``AGENTS.md``, ``CLAUDE.md``) are not in it: that build loads them as prompt text only.
DISCOVERY_PATHS = (".agents", ".claude", ".cursor", ".grok", ".mcp.json")
#: Erratum 3: the closed list of refusals that do not disqualify a measurement. Each is an
#: exact proxy observation -- method, host, path (``None`` for a ``CONNECT``) -- and counts
#: only when denied: the startup fetch of remote settings, and the updater's release check
#: and artifact host. Pinned by a test; adding an entry needs an erratum. It qualifies a
#: measurement, constrains no launch, and is not part of the context digest.
TOLERATED_REFUSALS = (
    ("GET", "cli-chat-proxy.grok.com", "/v1/settings"),
    ("CONNECT", "x.ai", None),
    ("CONNECT", "storage.googleapis.com", None),
)
EGRESS_ALLOWLIST_ID = "grok-review"
COMPOSITION = "panel_invoker.seat_profile+launch_owned:provider-review"
#: Erratum 8: the seat config, the one file besides the projection that a grok seat's private
#: home holds under the ``grok-review`` proxy. Harness-written and byte-exact: a pinned local
#: entry for the measurement model, and the client's own remote catalog fetch switched off.
#: :func:`seat_config` composes the bytes; this is their digest, and a build whose constants
#: no longer compose them projects nothing.
SEAT_CONFIG_RELATIVE = ".grok/config.toml"
SEAT_CONFIG_SHA256 = "2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780"
SEAT_CONFIG_SIZE = 424
#: Erratum 8, item 1b: the one projection, an immutable read-only data mount (a mount point
#: the seat can neither write, replace nor remove), from a sealed memfd.
SEAT_CONFIG_PROJECTION = "ro-bind-data"
SEAT_CONFIG_MODE = "0444"
#: The client's default backend; its endpoint is the path of the one ``grok-review`` allow row.
SEAT_CONFIG_API_BACKEND = "chat_completions"
#: The effort rows the entry declares; without them the client ignores ``--reasoning-effort``.
SEAT_CONFIG_EFFORTS = ("low", "medium", "high")
#: The seals ``seat_jail.memfd_with`` puts on the config's descriptor, exactly: F_SEAL_SEAL,
#: F_SEAL_SHRINK, F_SEAL_GROW and F_SEAL_WRITE (``fcntl``'s values on Linux, spelled out for
#: an interpreter without them).
_F_GET_SEALS = 1034
_CONFIG_SEALS = 0x1 | 0x2 | 0x4 | 0x8
#: Erratum 8, item 1c: the inputs that decide the inference route and body, the policy and
#: the offered tools, which must not change during a launch. Relative paths are in the seat
#: home; absolute ones are the host's. The derivation (the documentation bundled in 1.0.92 and
#: launch 7's file-call trace) is recorded in ``tests/test_grok_tool_surface.py``
#: (``test_the_pinned_fixed_inputs``). Project discovery is :data:`DISCOVERY_PATHS`, and the
#: environment and argv are fixed by ``exec``. ``.grok/config.toml`` is bound by its digest;
#: every other entry must be absent from the seat's view at the final check.
SEAT_FIXED_INPUTS = (
    # Policy layers.
    ".grok/config.toml", ".grok/managed_config.toml", ".grok/requirements.toml",
    "/etc/grok/managed_config.toml", "/etc/grok/requirements.toml",
    "/etc/claude-code/managed-settings.json",
    # Managed-sync state, and client caches that can carry configuration.
    ".grok/managed_config_cache.json", ".grok/managed_config.sig.json",
    ".grok/managed_identity.sig.json", ".grok/staged/managed_config_refresh.json",
    ".grok/models_cache.json", ".grok/experiments_state.json", ".grok/campaigns_state.json",
    # Discovery sources in the home.
    ".grok/skills", ".grok/agents", ".grok/bundled/agents", ".grok/bundled/skills",
    ".grok/commands", ".grok/plugins", ".grok/installed-plugins", ".grok/hooks",
    ".grok/hooks-paths", ".grok/disabled-hooks", ".grok/workflows", ".grok/lsp.json",
    ".grok/sandbox.toml", ".grok/trusted-plugins", ".grok/trusted-hook-projects",
    ".grok/trusted_folders.toml", ".grok/mcp_preferences.json", ".grok/mcp_credentials.json",
    ".grok/settings.json",
    ".claude.json", ".claude", ".cursor", ".agents", ".mcp.json", ".config/grove",
)
#: Pinned with the tuple: read by the client but bound by another check instead. The two
#: credential files by their own projection (:func:`_check_home`); ``.grok/rules`` (home and
#: project) is a rules source, prompt text under §4.4's rule for rules files.
SEAT_FIXED_INPUT_EXCLUSIONS = (".grok/agent_id", ".grok/auth.json", ".grok/rules")
#: Erratum 8, item 1d: the tool names a frozen-basis launch may offer at use. Under such a
#: surface the seat has no writing tool, so nothing but the client writes in the home. The
#: empty set qualifies (``sealed``'s ``--tools ""``); ``staged`` never does.
NON_MUTATING_TOOLS = ("read_file", "list_dir", "grep", "search_tool")

_ISSUER = object()


class _Refused(ValueError):
    """A record or a launch context failed one rule."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _strict_object(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise _Refused("duplicate key")
    return dict(pairs)


def _loads(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)


def _hex64(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _require(condition: bool) -> None:
    if not condition:
        raise _Refused("record refused")


def _check_route(route: object) -> None:
    _require(type(route) is dict and set(route) == _ROUTE_KEYS)
    assert isinstance(route, dict)
    _require(type(route["route"]) is str and _LABEL.fullmatch(route["route"]) is not None)
    _require(_hex64(route["argv_digest"]) and _hex64(route["definitions_sha256"]))
    tools = route["tools"]
    _require(type(tools) is list and all(type(tool) is str and _TOOL.fullmatch(tool) for tool in tools))
    # Sorted and de-duplicated; an empty list is valid evidence (§3.1, "Empty lists").
    _require(tools == sorted(set(tools)))


def _check_surface(surface: object) -> None:
    _require(type(surface) is dict and set(surface) == _SURFACE_KEYS)
    assert isinstance(surface, dict)
    for key in ("binary_sha256", "version_sha256", "help_sha256", "context_digest"):
        _require(_hex64(surface[key]))
    _require(type(surface["version"]) is str and bool(surface["version"].strip()))
    for key in ("model", "effort"):
        _require(type(surface[key]) is str and _LABEL.fullmatch(surface[key]) is not None)
    _require(surface["context"] == GROK_SEAT_CONTEXT)
    _require(type(surface["measured_at"]) is str and _UTC.fullmatch(surface["measured_at"]) is not None)
    routes = surface["routes"]
    _require(type(routes) is list)
    for route in routes:
        _check_route(route)
    digests = [route["argv_digest"] for route in routes]
    _require(len(digests) == len(set(digests)))


@dataclass(frozen=True)
class Catalog:
    revoked: frozenset[str]
    surfaces: Mapping[str, Mapping[str, Any]]


def parse_catalog(raw: bytes) -> Catalog:
    """The catalog in ``raw``, or :class:`_Refused` (a ``ValueError``). One bad entry voids
    the whole file (§3.1)."""
    _require(len(raw) <= CATALOG_MAX_BYTES)
    document = _loads(raw)
    _require(type(document) is dict and set(document) == {"schema", "revoked", "surfaces"})
    assert isinstance(document, dict)
    _require(document["schema"] == CATALOG_SCHEMA)
    revoked, surfaces = document["revoked"], document["surfaces"]
    _require(type(revoked) is list and all(_hex64(digest) for digest in revoked))
    _require(type(surfaces) is list)
    by_binary: dict[str, Mapping[str, Any]] = {}
    for surface in surfaces:
        _check_surface(surface)
        binary = surface["binary_sha256"]
        _require(binary not in by_binary and binary not in revoked)
        by_binary[binary] = surface
    return Catalog(revoked=frozenset(revoked), surfaces=by_binary)


def _catalog_bytes() -> bytes:
    resource = resources.files(__package__).joinpath("data", CATALOG_NAME)
    with resource.open("rb") as source:
        return source.read(CATALOG_MAX_BYTES + 1)


def load_catalog() -> Catalog | None:
    """The shipped catalog, read only through ``importlib.resources``; ``None`` on any
    refusal (§3.1)."""
    try:
        return parse_catalog(_catalog_bytes())
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def host_record_name(binary_sha256: str) -> str:
    return "grok-surface-" + binary_sha256 + ".json"


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size <= limit:
        chunk = os.read(descriptor, limit + 1 - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def load_host_record(binary_sha256: str) -> Mapping[str, Any] | None:
    """The host-local measured surface for ``binary_sha256`` (§3.2), or ``None``.

    Read with the checks ``grok_tool_gate`` applies to receipts: the record directory is
    the operator's and 0700, the file a regular 0600 file of the operator's, opened without
    following a link and read with a bound. It is refused unless it was written for this
    host. It is as trustworthy as the operator UID, and no more."""
    if not _hex64(binary_sha256):
        return None
    from .president_adapter import private_record_root
    from .seat_window import _host_digest

    try:
        directory = os.open(private_record_root(),
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            return None
        try:
            descriptor = os.open(host_record_name(binary_sha256),
                                 os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                 dir_fd=directory)
        except OSError:
            return None
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                return None
            raw = _read_bounded(descriptor, HOST_RECORD_MAX_BYTES)
        finally:
            os.close(descriptor)
    except OSError:
        return None
    finally:
        os.close(directory)
    try:
        _require(len(raw) <= HOST_RECORD_MAX_BYTES)
        document = _loads(raw)
        _require(type(document) is dict and set(document) == {"schema", "host_digest", "surface"})
        assert isinstance(document, dict)
        _require(document["schema"] == HOST_RECORD_SCHEMA)
        _require(_hex64(document["host_digest"]) and document["host_digest"] == _host_digest())
        surface = document["surface"]
        _check_surface(surface)
        _require(surface["binary_sha256"] == binary_sha256)
    except (ValueError, TypeError, RecursionError):
        return None
    return surface


def surface_digest(surface: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON of the record route used: its surface entry with
    ``routes`` replaced by that one route, so the binding fields are covered too."""
    bound = {key: value for key, value in surface.items() if key != "routes"}
    bound["route"] = dict(route)
    return sha256(_canonical(bound)).hexdigest()


@dataclass(frozen=True)
class FrozenSurface:
    surface: Mapping[str, Any]
    route: Mapping[str, Any]
    source: str
    surface_digest: str
    shadowed: str | None = None

    @property
    def tools(self) -> list[str]:
        return list(self.route["tools"])

    def receipt_fields(self) -> dict[str, str]:
        return {"surface_digest": self.surface_digest, "surface_source": self.source,
                "context": self.surface["context"], "context_digest": self.surface["context_digest"]}


def _route_for(surface: Mapping[str, Any] | None, argv_digest: str) -> Mapping[str, Any] | None:
    if surface is None:
        return None
    return next((route for route in surface["routes"] if route["argv_digest"] == argv_digest), None)


def frozen_surface(binary_sha256: str, argv_digest: str, *, version_sha256: str | None = None,
                   help_sha256: str | None = None) -> FrozenSurface | None:
    """The record for ``(binary_sha256, argv_digest)`` by §3.2 precedence, or ``None``.

    With ``version_sha256`` and ``help_sha256`` (the probe's own reads, §4.1) the record is
    accepted only if it was measured on those exact outputs. A refused catalog voids every
    source, since its ``revoked`` list cannot be known."""
    catalog = load_catalog()
    if (catalog is None or not _hex64(binary_sha256) or not _hex64(argv_digest)
            or binary_sha256 in catalog.revoked):
        return None
    shipped = catalog.surfaces.get(binary_sha256)
    shipped_route = _route_for(shipped, argv_digest)
    host = load_host_record(binary_sha256)
    host_route = _route_for(host, argv_digest)
    if host is not None and host_route is not None and not host_route_current(
            binary_sha256, argv_digest, surface_digest(host, host_route)):
        host_route = None  # withdrawn by a newer attempt, or published by no register entry
    if shipped is not None and shipped_route is not None:
        chosen = FrozenSurface(shipped, shipped_route, "catalog", surface_digest(shipped, shipped_route))
        if host is not None and host_route is not None and \
                surface_digest(host, host_route) != chosen.surface_digest:
            chosen = replace(chosen, shadowed="host_local")
    elif host is not None and host_route is not None:
        chosen = FrozenSurface(host, host_route, "host_local", surface_digest(host, host_route))
    else:
        return None
    if version_sha256 is not None and chosen.surface["version_sha256"] != version_sha256:
        return None
    if help_sha256 is not None and chosen.surface["help_sha256"] != help_sha256:
        return None
    return chosen


def egress_allowlist_digest() -> str:
    """The ``grok-review`` allow-list's content digest. Raises while lane L2a has not
    shipped it."""
    from . import seat_egress_proxy

    return seat_egress_proxy.allowlist_ref(EGRESS_ALLOWLIST_ID).content_digest


def _seat_config_bytes() -> bytes:
    """The seat config as this build composes it (erratum 8, item 1): the table key and
    ``model`` from :data:`MEASUREMENT_MODEL`, ``base_url`` from :data:`INFERENCE_HOST`, the
    default backend, the effort rows, and ``remote_fetch`` off."""
    model = MEASUREMENT_MODEL
    lines = [f'[model."{model}"]', f'model = "{model}"', f'name = "{model} (pinned local entry)"',
             f'base_url = "https://{INFERENCE_HOST}/v1"',
             f'api_backend = "{SEAT_CONFIG_API_BACKEND}"', ""]
    for effort in SEAT_CONFIG_EFFORTS:
        lines += [f'[[model."{model}".reasoning_efforts]]', f'value = "{effort}"',
                  f'label = "{effort.capitalize()} Effort"', ""]
    lines += ["[features]", "remote_fetch = false", ""]
    return "\n".join(lines).encode("ascii")


def seat_config() -> bytes:
    """The pinned seat config: the composed bytes, only while they are the pinned ones and
    the measurement effort is one the entry declares."""
    data = _seat_config_bytes()
    _require(sha256(data).hexdigest() == SEAT_CONFIG_SHA256
             and MEASUREMENT_EFFORT in SEAT_CONFIG_EFFORTS)
    return data


def seat_config_descriptor() -> int:
    """A memfd holding the pinned seat config from ``seat_jail.memfd_with``: sealed against
    write, grow, shrink and further sealing, positioned at its start, so the bytes behind
    the projection cannot change after this returns. A build that no longer composes the
    pinned bytes gets no descriptor (``grok_tool_surface_unverified``)."""
    from .seat_jail import SeatSandboxRefused, memfd_with

    try:
        data = seat_config()
    except _Refused as exc:
        raise SeatSandboxRefused("grok_tool_surface_unverified") from exc
    return memfd_with("seat-config", data)


def seat_config_projection(descriptor: int) -> tuple[str, ...]:
    """The one triple that projects the seat config from ``descriptor`` (erratum 8, item
    1b): bubblewrap reads the descriptor while it sets up and bind-mounts the result
    read-only at ``.grok/config.toml``. ``seat_profile`` composes exactly these words and
    the home check admits exactly these."""
    return ("--perms", SEAT_CONFIG_MODE, "--" + SEAT_CONFIG_PROJECTION, str(int(descriptor)),
            PRIVATE_HOME + "/" + SEAT_CONFIG_RELATIVE)


def _allow_list(command) -> list[str] | None:
    """The names of ``command``'s one ``--tools`` allow-list; ``None`` without exactly one."""
    words = [str(word) for word in command]
    found = [index for index, word in enumerate(words[:-1]) if word == "--tools"]
    if len(found) != 1 or "--tools" in words[-1:]:
        return None
    return [name for name in words[found[0] + 1].split(",") if name]


def eligible_at_use(command, admitted) -> bool:
    """Erratum 8, item 1d: may a frozen-basis receipt admit a launch of ``command`` under
    ``grok_seat_context.v1``? Only a form whose allow-list and whose receipt's ``admitted``
    names both stay within :data:`NON_MUTATING_TOOLS`, so no tool in the seat can write a
    fixed input. ``staged`` (its run and write tools) is ineligible at use; it may still be
    measured, which this never decides."""
    allowed = _allow_list(command)
    return (allowed is not None and isinstance(admitted, list)
            and all(type(name) is str for name in admitted)
            and set(allowed) <= set(NON_MUTATING_TOOLS)
            and set(admitted) <= set(NON_MUTATING_TOOLS))


def context_document(allowlist_digest: str) -> dict[str, object]:
    return {
        "schema": GROK_SEAT_CONTEXT,
        "home": PRIVATE_HOME,
        "seat_config": {"path": SEAT_CONFIG_RELATIVE,
                        "sha256": sha256(_seat_config_bytes()).hexdigest(),
                        "projection": SEAT_CONFIG_PROJECTION},
        "fixed_inputs": list(SEAT_FIXED_INPUTS),
        "non_mutating_tools": list(NON_MUTATING_TOOLS),
        "projected_paths": sorted((*PROJECTED_PATHS, *PROXY_PROJECTED_PATHS)),
        "environment": {"allowed": sorted((*ENVIRONMENT, *PROXY_ENVIRONMENT)),
                        "forbidden_prefixes": list(FORBIDDEN_ENVIRONMENT_PREFIXES)},
        "managed_config": list(MANAGED_CONFIG_PATHS),
        "child_absent_policy": list(CHILD_ABSENT_POLICY_PATHS),
        "discovery": list(DISCOVERY_PATHS),
        "egress": {"allowlist_id": EGRESS_ALLOWLIST_ID, "content_digest": allowlist_digest},
        "composition": COMPOSITION,
    }


def context_digest() -> str:
    """sha256 of the canonical JSON of ``grok_seat_context.v1`` as this code enforces it."""
    return sha256(_canonical(context_document(egress_allowlist_digest()))).hexdigest()


@dataclass(frozen=True)
class ProvisionalContext:
    """A profile composed for a grok argv whose receipt is on the frozen basis. It passed
    the provisional step only (§4.4, step 1): it admits composition, never a launch."""

    command: tuple[str, ...]


@dataclass(frozen=True)
class LaunchContext:
    """The mark :func:`verify_launch_context` gives a composed profile (§4.4, step 2).
    ``launch_owned`` admits a frozen-basis grok launch only on a profile carrying one that
    still matches the launch: the same argv after its executable (so the ``--cwd`` and
    ``--add-dir`` the discovery check judged), the same cwd, profile, egress and record."""

    command: tuple[str, ...]
    context_digest: str
    cwd: str
    egress_prefix: tuple[str, ...]
    profile_fingerprint: str
    #: The frozen receipt the final check judged (erratum 8, item 1d): its admitted tool
    #: names and surface digest, which the launch's own receipt must still carry.
    admitted_tools: tuple[str, ...] = ()
    surface_digest: str = ""
    proxy: object = field(default=None, repr=False, compare=False)
    issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.issuer is not _ISSUER:
            raise TypeError("a launch context is issued only by verify_launch_context")


def is_issued(context: object) -> bool:
    return isinstance(context, LaunchContext) and context.issuer is _ISSUER


def profile_fingerprint(profile: Any) -> str:
    """What a mark binds to: the composed profile's launch-relevant fields."""
    return sha256(_canonical({
        "env": dict(profile.env),
        "mount_args": list(profile.mount_args),
        "readonly_paths": [str(path) for path in profile.readonly_paths],
        "outputs": [str(path) for path in profile.outputs],
        "writable_trees": [str(path) for path in profile.writable_trees],
        "output_dirs": [list(item) for item in profile.output_dirs],
        "broker_socket": None if profile.broker_socket is None else str(profile.broker_socket),
        "pass_fds": list(profile.pass_fds),
        "keep_fds": list(profile.keep_fds),
        "terminal_fd": profile.terminal_fd,
        "dependency_projection_digest": profile.dependency_projection_digest,
    })).hexdigest()


_MOUNT_ARITY = {"--tmpfs": 1, "--perms": 1, "--dir": 1, "--file": 2, "--ro-bind": 2,
                "--ro-bind-try": 2, "--bind": 2, "--bind-try": 2, "--ro-bind-data": 2,
                "--bind-data": 2, "--symlink": 2}


#: The operations that copy their file from a descriptor (the first operand).
_DATA_OPERATIONS = frozenset({"--file", "--bind-data", "--ro-bind-data"})


def _mounts(arguments) -> list[tuple[str, tuple[str, ...]]]:
    arguments = list(arguments)
    mounts = []
    index = 0
    while index < len(arguments):
        operation = arguments[index]
        arity = _MOUNT_ARITY.get(operation)
        _require(arity is not None and index + arity < len(arguments))
        assert arity is not None
        mounts.append((operation, tuple(arguments[index + 1:index + 1 + arity])))
        index += 1 + arity
    return mounts


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _normalised(path: str) -> str:
    """``path`` as one spelling: absolute, with ``.``, ``..`` and repeated slashes resolved."""
    return "/" + os.path.normpath("/" + path).lstrip("/")


def _config_mount(mounts) -> tuple[str, ...]:
    """The one operation at the seat config's path and the operation before it (its
    ``--perms``), as the words ``seat_profile`` composed. A missing operation, or a second
    one whose destination, normalised, is that path or below it, refuses; so does the one
    operation spelt any other way."""
    destination = PRIVATE_HOME + "/" + SEAT_CONFIG_RELATIVE
    found = [index for index, (operation, operands) in enumerate(mounts)
             if operation != "--perms" and _inside(_normalised(operands[-1]), destination)]
    _require(len(found) == 1)
    (index,) = found
    _require(mounts[index][1][-1] == destination)
    return tuple(word for operation, operands in mounts[max(index - 1, 0):index + 1]
                 for word in (operation, *operands))


def _config_descriptor(composed: tuple[str, ...]) -> int:
    """The descriptor a composed config mount names; an operation that names none refuses."""
    try:
        return int(composed[-2])
    except ValueError as exc:
        raise _Refused("no descriptor behind the seat config") from exc


def _check_home(profile: Any, sessions: str | None = None) -> None:
    """Home: nothing in the fresh private home but the projection (§4.4): the credential
    files, the proxy projection's read-only CA file, the seat config of erratum 8 in the
    one mode :func:`seat_config_projection` composes and, for a measurement only, its one
    scratch sessions directory (§5.1), bound from ``sessions``. Every destination is a
    normalised absolute path, and none is the home itself or above it."""
    home = PRIVATE_HOME
    credentials = {home + "/" + relative for relative in PROJECTED_PATHS}
    projected = {home + "/" + relative for relative in PROXY_PROJECTED_PATHS}
    config = home + "/" + SEAT_CONFIG_RELATIVE
    files = credentials | projected | {config}
    directories = {home + "/.config", home + "/.cache", home + "/.local", home + "/.local/share"}
    for path in files:
        parent = os.path.dirname(path)
        while parent != home:
            directories.add(parent)
            parent = os.path.dirname(parent)
    mounts = _mounts(profile.mount_args)
    _require(bool(mounts) and mounts[0] == ("--tmpfs", (home,)))
    composed = _config_mount(mounts)
    _require(composed == seat_config_projection(_config_descriptor(composed)))
    seen: list[str] = []
    bound: list[tuple[str, ...]] = []
    for operation, operands in mounts[1:]:
        if operation == "--perms":
            continue
        destination = operands[-1]
        # One spelling per path, so a destination is inside the home exactly when it reads
        # so; and after the home's own tmpfs nothing is mounted at or above the home.
        _require(destination.startswith("/") and not destination.startswith("//")
                 and os.path.normpath(destination) == destination)
        _require(not _inside(home, destination))
        _require(not _inside(destination, "/etc/grok"))
        if operation == "--tmpfs":
            raise _Refused("a second tmpfs")
        if not _inside(destination, home):
            continue
        if destination == config:
            seen.append(destination)  # its one mode was judged above
        elif operation == "--dir":
            _require(destination in directories)
        elif operation == "--file":
            _require(destination in credentials)
            seen.append(destination)
        elif operation == "--ro-bind-data":
            _require(destination in projected)
            seen.append(destination)
        elif operation == "--bind" and sessions is not None:
            bound.append(operands)
        else:
            raise _Refused("a host path in the private home")
    _require(sorted(seen) == sorted(files))
    if sessions is not None:
        _require(len(bound) == 1 and bound[0][1] == home + "/" + SESSIONS_RELATIVE
                 and os.path.realpath(bound[0][0]) == os.path.realpath(sessions))
    env = profile.env
    _require(env.get("HOME") == home and env.get("XDG_CONFIG_HOME") == home + "/.config"
             and env.get("XDG_CACHE_HOME") == home + "/.cache"
             and env.get("XDG_DATA_HOME") == home + "/.local/share")


def _check_seat_config(profile: Any) -> None:
    """The descriptor bubblewrap consumes for the seat config, before the launch (erratum 8,
    item 1b): the one it reads is the one the profile's config triple names, and it is
    passed to the launch (not kept), a memfd carrying exactly the four seals (asking for the
    seals of anything else fails), :data:`SEAT_CONFIG_SIZE` bytes long, at its start, and
    holding exactly the pinned config. The bytes are read at an offset, never consumed: a
    descriptor left at its end would hand bubblewrap an empty file."""
    import fcntl

    mounts = _mounts(profile.mount_args)
    descriptor = _config_descriptor(_config_mount(mounts))
    _require(descriptor in tuple(profile.pass_fds))
    _require(descriptor not in tuple(profile.keep_fds))
    # One consumer: bubblewrap copies every data mount from the descriptor it names, so the
    # config's descriptor is named by its own triple and nothing else -- by number in no
    # other operation and not as the terminal, and no other descriptor passed or kept is
    # the same file (a duplicate shares its offset; a reopened path shares its bytes).
    _require(sum(1 for operation, operands in mounts if operation in _DATA_OPERATIONS
                 and operands[0] == str(descriptor)) == 1)
    _require(profile.terminal_fd != descriptor)
    config_file = os.fstat(descriptor)
    for other in {*profile.pass_fds, *profile.keep_fds} - {descriptor}:
        try:
            info = os.fstat(other)
        except OSError:
            continue  # not open here, so not this file; the launch refuses it anyway
        _require((info.st_dev, info.st_ino) != (config_file.st_dev, config_file.st_ino))
    # Only a memfd created to allow sealing can carry these seals; anything else either
    # fails the request or reports F_SEAL_SEAL alone.
    seals = fcntl.fcntl(descriptor, getattr(fcntl, "F_GET_SEALS", _F_GET_SEALS))
    _require(seals == _CONFIG_SEALS)
    _require(os.fstat(descriptor).st_size == SEAT_CONFIG_SIZE)
    _require(os.lseek(descriptor, 0, os.SEEK_CUR) == 0)
    # seat_config() refuses unless its bytes hash to SEAT_CONFIG_SHA256, so equal bytes are
    # the digest check.
    _require(os.pread(descriptor, SEAT_CONFIG_SIZE, 0) == seat_config())


def _check_fixed_inputs(mounts) -> None:
    """Erratum 8, item 1c: every fixed input but the seat config, which its digest binds, is
    absent from the seat's view at the final check, judged on the view the launch composes,
    so nothing the profile, its outputs or its read-only paths add can supply one."""
    for entry in SEAT_FIXED_INPUTS:
        if entry == SEAT_CONFIG_RELATIVE:
            continue
        path = entry if entry.startswith("/") else PRIVATE_HOME + "/" + entry
        _require(not _visible(path, mounts))


def _check_environment(env: Mapping[str, str]) -> None:
    allowed = {*ENVIRONMENT, *PROXY_ENVIRONMENT}
    for key in env:
        _require(key in allowed and not key.startswith(FORBIDDEN_ENVIRONMENT_PREFIXES))


@dataclass(frozen=True)
class _Mount:
    """One operation of the seat's view, in launch order, as bubblewrap applies it:

    - ``bind``: a host path bound from ``source``; it replaces the view at ``destination``
      (a missing source fails the launch);
    - ``bind_try``: the same, but skipped when its source is missing;
    - ``tmpfs`` and ``special`` (``--dev``, ``--proc``): a fresh mount of the seat's own;
    - ``dir``: creates a directory where there is none, and hides nothing;
    - ``data``: a file whose bytes come from a descriptor;
    - ``unevaluable``: a link, or anything else."""

    destination: str
    kind: str
    source: str | None = None


_KINDS = {"--ro-bind": "bind", "--bind": "bind", "--ro-bind-try": "bind_try",
          "--bind-try": "bind_try", "--tmpfs": "tmpfs", "--dev": "special", "--proc": "special",
          "--dir": "dir", "--file": "data", "--ro-bind-data": "data", "--bind-data": "data"}


def _mount(operation: str, operands) -> _Mount:
    kind = _KINDS.get(operation, "unevaluable")
    return _Mount(os.path.abspath(operands[-1]), kind,
                  operands[0] if kind in {"bind", "bind_try"} else None)


def _effective_mounts(panel: Any, profile: Any, cwd: str) -> list[_Mount]:
    """The seat's view as ``launch_owned`` composes it (``panel_invoker._seat_filesystem_view``):
    the base layers with each output directory inserted after the last mount at or above it,
    then the outputs, the broker socket, the keyring and the profile's own mounts."""
    from . import seat_keyring_exec

    layers = panel._seat_view_layers(cwd, profile.readonly_paths, check=False,
                                     writable_trees=profile.writable_trees)
    for source, destination in sorted(
            profile.output_dirs, key=lambda item: os.path.abspath(item[1]).count("/")):
        destination = os.path.abspath(destination)
        anchor = panel._seat_output_anchor(layers, destination)
        _require(anchor is not None)  # the launch refuses this layout too
        # The seat's own directory, as the launch marks it; its host source is judged below.
        layers.insert(anchor + 1, (destination, True, ["--bind", source, destination]))
    mounts = [_mount(arguments[0], arguments[1:]) for _destination, _private, arguments in layers]
    mounts += [_Mount(os.path.abspath(str(path)), "bind", str(path)) for path in profile.outputs]
    if profile.broker_socket is not None:
        mounts.append(_Mount(os.path.abspath(str(profile.broker_socket)), "bind",
                             str(profile.broker_socket)))
    mounts.append(_Mount("/run/phase-loop-seat/keyring.py", "bind",
                         str(os.path.realpath(seat_keyring_exec.__file__))))
    mounts += [_mount(operation, operands) for operation, operands in _mounts(profile.mount_args)
               if operation != "--perms"]
    return mounts


def _through(bind: _Mount, path: str) -> str:
    """What ``bind`` shows at ``path`` below its destination: ``absent``, ``present`` or
    ``unknown``. The source is opened as the launch binds it; below it the walk opens one
    component at a time and never follows a link, so a link on the way is ``unknown``. A
    link at ``path`` itself is ``present``."""
    assert bind.source is not None
    parts = [part for part in path[len(bind.destination.rstrip("/")):].split("/") if part]
    try:
        descriptor = os.open(os.path.realpath(bind.source), os.O_PATH | os.O_CLOEXEC)
    except OSError:
        return "unknown"  # a bind without its source: not modelled
    try:
        for index, part in enumerate(parts):
            try:
                info = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except (FileNotFoundError, NotADirectoryError):
                return "absent"
            except OSError:
                return "unknown"
            if index == len(parts) - 1:
                return "present"
            if stat.S_ISLNK(info.st_mode):
                return "unknown"
            if not stat.S_ISDIR(info.st_mode):
                return "absent"
            try:
                child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            except OSError:
                return "unknown"
            os.close(descriptor)
            descriptor = child
        return "present"
    finally:
        os.close(descriptor)


def _visible(path: str, mounts) -> bool:
    """Can the seat see ``path`` in the view ``mounts``? ``False`` only when its absence is
    proved; every overlap this does not model counts as visible, so it refuses.

    - Anything mounted or created at ``path``, or below it, makes it visible.
    - The operations at or above it apply in order from the bare root, which shows nothing.
      A bind replaces the view and is judged on its source. A ``--dir`` hides nothing.
    - Refused, not modelled: a link or a ``-try`` bind at or above it, a link inside a bound
      source on the way to it, and a tmpfs, special or data mount over a view in which an
      earlier bind showed it."""
    path = os.path.abspath(path)
    above = []
    for mount in mounts:
        if mount.destination == path or mount.destination.startswith(path.rstrip("/") + "/"):
            return True
        if _inside(path, mount.destination):
            above.append(mount)
    shown = False
    for mount in above:
        if mount.kind in {"unevaluable", "bind_try"}:
            return True
        if mount.kind == "bind":
            seen = _through(mount, path)
            if seen == "unknown":
                return True
            shown = seen == "present"
        elif mount.kind == "dir":
            continue
        elif shown:
            return True  # a mount over a view that showed it: refused, not modelled
    return shown


def _present(path: str) -> bool:
    """Is anything at ``path``, read with ``lstat``? Absent only on ``FileNotFoundError`` or
    ``NotADirectoryError``: a dangling link, and any other access error, count as present."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return True


def managed_policy_staging() -> dict[str, object]:
    """Erratum 8, item 4: the read-only staging check, before a grant opens (run by
    ``--verify-probe initial``; it launches and reads nothing else). It uses the launch
    guard's own rule (:func:`_present`): staging stops if either grok managed path is
    present, a dangling link included, and it records whether Claude Code's managed
    settings exist on the host, which is allowed (the launch check proves them hidden from
    the child). Preliminary: the launch check binds."""
    present = [path for path in MANAGED_CONFIG_PATHS if _present(path)]
    return {"passed": not present, "grok_managed_present": present,
            "claude_managed_settings_present": any(_present(path)
                                                   for path in CHILD_ABSENT_POLICY_PATHS)}


def _check_managed_config(mounts) -> None:
    """Managed config: grok's own is absent on the host and from the child's view; Claude's
    managed settings are absent from the child's view (§4.4)."""
    for path in MANAGED_CONFIG_PATHS:
        if _present(path):
            raise _Refused("managed configuration is present")
    for path in (*MANAGED_CONFIG_PATHS, *CHILD_ABSENT_POLICY_PATHS):
        _require(not _visible(path, mounts))


def _discovery_directories(command, cwd: str) -> list[str]:
    directories = [cwd]
    for index, word in enumerate(command[:-1]):
        if word in {"--cwd", "--add-dir"}:
            value = command[index + 1]
            directories.append(os.path.abspath(os.path.join(cwd, value)))
    return directories


def _check_discovery(mounts, cwd: str, command) -> None:
    """Project discovery: the launch cwd, each ``--cwd`` and ``--add-dir``, and each of their
    ancestors the seat can see hold none of the pinned discovery paths (§4.4), judged on the
    view the launch composes. The staged tree is judged as it is; it is never rewritten."""
    for directory in _discovery_directories(command, cwd):
        ancestor = directory
        while True:
            for name in DISCOVERY_PATHS:
                _require(not _visible(os.path.join(ancestor, name), mounts))
            if ancestor == "/":
                break
            ancestor = os.path.dirname(ancestor)


def _check_egress(panel: Any, proxy: object) -> tuple[str, ...]:
    """Egress: this launch's own proxy under the ``grok-review`` allow-list, and the
    proxy-only namespace held as the launch's egress prefix, which is not the host's.

    Binding that holder to the socket of this proxy (contract §10, BA-3) is
    :func:`bridged_to`, one check shared by both paths:
    - the measurement: its admission, :func:`verify_measurement_context` and the isolation
      self-check;
    - the board leg (``panel_invoker``): its egress setup, its final step before this
      check, and ``launch_owned``'s final admission of the marked profile.
    It is not checked here, so a mark from :func:`verify_launch_context` alone is not bound."""
    from .seat_egress_proxy import SeatEgressProxy

    _require(isinstance(proxy, SeatEgressProxy))
    assert isinstance(proxy, SeatEgressProxy)
    _require(proxy.allowlist_id == EGRESS_ALLOWLIST_ID
             and proxy.allowlist_digest == egress_allowlist_digest())
    _require(bool(proxy.socket) and proxy.process.poll() is None)
    prefix = tuple(panel._EGRESS_LAUNCH_PREFIX.get())
    _require(bool(prefix))
    panel._filtered_holder_namespace()
    return prefix


def _check_proxy_projection(profile: Any, proxy: Any) -> None:
    """The child reaches the network through this launch's own proxy, trusting its CA
    (§5.2): the projection names exactly that proxy and the projected CA file."""
    env = profile.env
    _require(env.get(PROXY_ENVIRONMENT[0]) == proxy.proxy_url
             and env.get(PROXY_ENVIRONMENT[1]) == PRIVATE_HOME + "/" + PROXY_PROJECTED_PATHS[0])


def _check_context(panel: Any, profile: Any, *, cwd, command, role, proxy, jailed: bool,
                   sessions: str | None = None) -> tuple[str, str, tuple[str, ...]]:
    """Every ``grok_seat_context.v1`` condition against a composed profile, the same at
    measurement (§5.4) and at use (§4.4). ``(context digest, cwd, egress prefix)``."""
    _require(not jailed)
    _require(panel.SeatLaunchRole(role) is panel.SeatLaunchRole.PROVIDER_REVIEW)
    current = context_digest()
    _check_home(profile, sessions)
    _check_seat_config(profile)
    _check_environment(profile.env)
    cwd = os.path.abspath(cwd)
    mounts = _effective_mounts(panel, profile, cwd)
    _check_managed_config(mounts)
    _check_fixed_inputs(mounts)
    _check_discovery(mounts, cwd, command)
    prefix = _check_egress(panel, proxy)
    _check_proxy_projection(profile, proxy)
    return current, cwd, prefix


def verify_launch_context(profile: Any, *, env: Mapping[str, str], cwd, role, proxy,
                          jailed: bool = False) -> Any:
    """The final check (§4.4, step 2): every ``grok_seat_context.v1`` condition against the
    composed ``profile``, the launch ``cwd`` and the proxy this launch owns. Returns the
    profile marked; any failure is ``grok_tool_surface_unverified``, with no fallback."""
    from . import panel_invoker as panel
    from .seat_jail import SeatSandboxRefused

    try:
        state = profile.grok_launch_context
        _require(isinstance(state, ProvisionalContext))
        current, cwd, prefix = _check_context(panel, profile, cwd=cwd, command=state.command,
                                              role=role, proxy=proxy, jailed=jailed)
        # The one receipt read: the frozen snapshot the gate itself validated.
        snapshot = panel._grok_frozen_snapshot(list(state.command), env)
        _require(snapshot is not None)
        assert snapshot is not None
        admitted, surface = snapshot
        # Erratum 8, item 1d: at use, only a form with no writing tool; `staged` is
        # ineligible under grok_seat_context.v1 and refused here, before any spawn.
        _require(eligible_at_use(state.command, list(admitted)))
        mark = LaunchContext(command=state.command, context_digest=current, cwd=cwd,
                             egress_prefix=prefix, profile_fingerprint=profile_fingerprint(profile),
                             admitted_tools=admitted, surface_digest=surface,
                             proxy=proxy, issuer=_ISSUER)
    except Exception as exc:  # noqa: BLE001 - every failure is the one public refusal (§4.6)
        raise SeatSandboxRefused("grok_tool_surface_unverified") from exc
    return replace(profile, grok_launch_context=mark)


_ACCEPTING = 0x10000  # __SO_ACCEPTCON in /proc/net/unix: a listening socket


def _listening_socket_held(pid: int, path: str) -> bool:
    """Is the one listening unix socket bound at ``path`` held open by process ``pid``?
    Read from ``/proc/<pid>/net/unix`` (its network namespace's sockets) and the process's
    own descriptors; two listeners at one path, or none, is ``False``."""
    inodes = set()
    with open(f"/proc/{int(pid)}/net/unix", encoding="ascii", errors="replace") as table:
        next(table, None)
        for line in table:
            fields = line.split()
            if (len(fields) >= 8 and fields[7] == path
                    and int(fields[3], 16) & _ACCEPTING):
                inodes.add(fields[6])
    if len(inodes) != 1:
        return False
    (inode,) = inodes
    folder = f"/proc/{int(pid)}/fd"
    for name in os.listdir(folder):
        with contextlib.suppress(OSError):
            if os.readlink(f"{folder}/{name}") == f"socket:[{inode}]":
                return True
    return False


def bridged_to(prefix, proxy) -> bool:
    """BA-3: does the exact live namespace holder behind ``prefix`` bridge to THIS proxy?

    The holder's pid is the one ``prefix`` enters. The bridge must be the one this process
    launched for that holder (``sandbox_egress``'s registry, never anything read from the
    child), still running, inside that holder's network namespace, and dialling exactly
    this proxy's socket; and that socket must be the one listener at its path, held by this
    proxy's own process. A copied prefix, URL or CA path proves none of that. Another live
    holder, or another live proxy with the same policy and budget, fails."""
    from . import sandbox_egress

    try:
        items = [str(item) for item in prefix]
        holder = items[items.index("-t") + 1]
        bridge = sandbox_egress._BRIDGES.get(holder)
        if bridge is None or bridge.poll() is not None:
            return False
        args = [str(item) for item in bridge.args]
        if (args[args.index("-t") + 1] != holder
                or f"UNIX-CONNECT:{proxy.socket}" not in args
                or proxy.process.poll() is not None):
            return False
        if (os.stat(f"/proc/{int(bridge.pid)}/ns/net").st_ino
                != os.stat(f"/proc/{int(holder)}/ns/net").st_ino):
            return False
        return _listening_socket_held(proxy.process.pid, str(proxy.socket))
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        return False


def verify_measurement_context(profile: Any, *, cwd, command, proxy, sessions: str) -> str:
    """Step 2 of a measurement launch (§5.4): every ``grok_seat_context.v1`` condition
    against the measurement's own composed profile, the same checks a launch relying on the
    record must pass (§4.4), with the scratch sessions directory as the only host-backed path
    in the home (§5.1). Returns the context digest. A measurement carries no mark: no record
    exists for it to rely on, and :class:`MeasurementAdmission` admits its one launch."""
    from . import panel_invoker as panel
    from .seat_jail import SeatSandboxRefused

    try:
        _require(getattr(profile, "grok_launch_context", None) is None)
        current, _cwd, prefix = _check_context(
            panel, profile, cwd=cwd, command=list(command),
            role=panel.SeatLaunchRole.PROVIDER_REVIEW, proxy=proxy, jailed=False,
            sessions=sessions)
        # BA-3: the namespace this launch will enter bridges to this launch's own proxy.
        _require(bridged_to(prefix, proxy))
    except Exception as exc:  # noqa: BLE001 - every failure is the one public refusal
        raise SeatSandboxRefused("grok_tool_surface_unverified") from exc
    return current


# ====================================================== the measurement (§5, lane L2b)

#: The seat forms the measurement launches (ruling C1: the executor forms are not measured).
MEASURED_ROUTES = ("review", "sealed", "staged")
EXECUTOR_ROUTES = ("execute", "workflow")
#: §4.4 and §5.8: the forms the board review leg launches through the measured composition
#: (wired by lane L2c, which lands before any measurement runs, contract §5.10). The
#: executor forms stay ineligible (follow-up F7).
ELIGIBLE_ROUTES = MEASURED_ROUTES
MEASUREMENT_MODEL = "grok-4.7"  # model-id-source: frozen measurement model per the plan's ruling D6
MEASUREMENT_EFFORT = "high"
MEASUREMENT_PROMPT = "Reply with the single word OK. Do not call any tool."  # §5.4
#: §5.3: one counted request per launch, a constant. A larger budget needs a revised grant.
PER_LAUNCH_BUDGET = 1
#: §5.3: the ceiling the ledger enforces on a grant, a constant.
GRANT_CAP = 7
LAUNCH_TIMEOUT_S = 180.0
INFERENCE_HOST = "cli-chat-proxy.grok.com"
DEFINITIONS_NAME = "tool_definitions.json"
DEFINITIONS_MAX_BYTES = 4 * 1024 * 1024
LOG_RETENTION_S = 7 * 24 * 3600
RAW_RETENTION_S = 30 * 24 * 3600
EXTRACTOR_REVISION = "grok_tool_names.v1"
GRANTS_DIRNAME = "grok-measure-grants"
GRANT_SCHEMA = "grok_tool_surface_grant.v1"
RESERVATION_SCHEMA = "grok_tool_surface_reservation.v1"
SETTLEMENT_SCHEMA = "grok_tool_surface_settlement.v1"
RESULT_SCHEMA = "grok_tool_surface_result.v1"
EVIDENCE_SCHEMA = "grok_tool_surface_evidence.v1"
ATTEMPTS_SCHEMA = "grok_tool_surface_attempts.v1"
REHEARSAL_SCHEMA = "grok_tool_surface_rehearsal.v1"
#: Erratum 4: why a rehearsal did not pass, in a closed vocabulary.
REHEARSAL_REASONS = ("passed", "context_refused", "launch_failed", "egress_refused",
                     "identity_changed", "observation_incomplete", "unlisted_request",
                     "no_model_request")
#: §5.8, in that order.
STATUSES = ("measured", "format_unrecognised", "artifact_missing", "artifact_ambiguous",
            "launch_failed", "egress_refused", "budget_exhausted", "identity_changed",
            "context_refused", "interrupted")

_GRANT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_RESERVATION_NAME = re.compile(r"(\d{4})-([0-9a-f]{16})\.json")
_RESULT_NAME = re.compile(r"(\d{4}-[0-9a-f]{16})(?:\.r(\d{1,3}))?\.json")
#: A result committed with the grant: ``results/<reservation>.<revision>.json``.
_COMMITTED_NAME = re.compile(r"(\d{4}-[0-9a-f]{16})\.(\d{1,3})\.json")
_KEY_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")
_VERSION_TEXT = re.compile(r"[ -~]{1,128}")
_RECORD_MAX_BYTES = 1024 * 1024
def _dir_flags() -> int:
    """The flags of every directory this module opens: read-only, a directory, never through
    a link, not inherited. They are resolved at use, not import, because ``panel_invoker``
    imports this module on every platform. Where one is missing no directory is opened: the
    ``OSError`` is each caller's existing refusal, so the guarantee is never dropped."""
    try:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    except AttributeError:
        raise OSError(errno.ENOTSUP, "no-follow directory opens are unavailable") from None


def _lock_now(descriptor: int) -> None:
    """An exclusive ``flock`` on ``descriptor``, taken without waiting: ``BlockingIOError``
    while another holder has it. ``fcntl`` is imported here, not at module import, for the
    same reason as :func:`_dir_flags`. Where it is missing no lock can be taken, so the
    ``OSError`` refuses and no caller proceeds unlocked."""
    try:
        import fcntl
    except ImportError:
        raise OSError(errno.ENOTSUP, "advisory locks are unavailable") from None
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
_STRUCTURE_NODES = 256
#: How long a writer waits for the per-binary publication lock before ``publication_busy``.
PUBLICATION_WAIT_S = 30.0


class MeasurementRefused(Exception):
    """A ``measure-tools`` stage refused; ``code`` is a closed slug and never carries a
    path, a provider string or a secret."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _refuse(code: str) -> MeasurementRefused:
    return MeasurementRefused(code)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii") + b"\n"


# ------------------------------------------------------------- private storage helpers

def _check_private_dir(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise _refuse("private_storage_unavailable")


def _open_tree(path: Path | str, *, create: bool) -> int:
    """``path`` opened component by component from ``/`` without following a link, its
    missing components created 0700 when ``create``; it must be ours and 0700."""
    parts = Path(os.path.abspath(path)).parts[1:]
    try:
        descriptor = os.open("/", _dir_flags())
    except OSError as exc:
        raise _refuse("private_storage_unavailable") from exc
    try:
        for part in parts:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=descriptor)
            child = os.open(part, _dir_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _check_private_dir(descriptor)
    except OSError as exc:
        os.close(descriptor)
        raise _refuse("private_storage_unavailable") from exc
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _subdir(parent: int, name: str, *, create: bool) -> int:
    try:
        if create:
            with contextlib.suppress(FileExistsError):
                os.mkdir(name, 0o700, dir_fd=parent)
        descriptor = os.open(name, _dir_flags(), dir_fd=parent)
    except OSError as exc:
        raise _refuse("private_storage_unavailable") from exc
    try:
        _check_private_dir(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _write_new(directory: int, name: str, data: bytes | Mapping[str, Any]) -> None:
    """An immutable private file: created exclusively, 0600, never through a link, the file
    and its directory fsynced."""
    payload = data if isinstance(data, bytes) else _encode(data)
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)


def _replace_file(directory: int, name: str, document: Mapping[str, Any]) -> None:
    """``name`` replaced atomically: a private temp file, then a rename over it."""
    temp = "." + name + "." + secrets.token_hex(8) + ".tmp"
    _write_new(directory, temp, document)
    try:
        os.rename(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp, dir_fd=directory)
        raise
    os.fsync(directory)


def _commit_new(directory: int, name: str, payload: bytes) -> None:
    """Commit an immutable file so that a crash at any point is recoverable: the bytes go
    to a private temp file first, which is then linked to ``name`` (``linkat`` fails if
    ``name`` exists, so a commit is exclusive) and removed. ``name`` is therefore either
    absent or complete, never partial, and a retry after a crash commits it cleanly. An
    existing ``name`` with these exact bytes is the same commit and succeeds."""
    temp = ".tmp-" + name + "." + secrets.token_hex(8)
    _write_new(directory, temp, payload)
    try:
        try:
            os.link(temp, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            if _read_file(directory, name, len(payload) + 1) != payload:
                raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=directory)
    os.fsync(directory)


def _remove_commit_temps(directory: int, *, older_than_s: float = 0.0) -> None:
    """Temp files a crashed :func:`_commit_new` left behind; never a committed name."""
    now = time.time()
    for name in os.listdir(directory):
        if name.startswith(".tmp-"):
            with contextlib.suppress(FileNotFoundError):
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if info.st_mtime <= now - older_than_s:
                    os.unlink(name, dir_fd=directory)


def _read_file(directory: int, name: str, limit: int) -> bytes:
    """A private regular file of ours, read through one no-follow descriptor with a bound.
    ``FileNotFoundError`` when absent; :class:`_Refused` when it is not a private file."""
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o600)
        raw = _read_bounded(descriptor, limit)
    finally:
        os.close(descriptor)
    _require(len(raw) <= limit)
    return raw


def _read_doc(directory: int, name: str, limit: int = _RECORD_MAX_BYTES) -> dict:
    document = _loads(_read_file(directory, name, limit))
    _require(type(document) is dict)
    assert isinstance(document, dict)
    return document


@contextlib.contextmanager
def _flock(directory: int, name: str, *, busy: str, wait_s: float = 0.0) -> Iterator[None]:
    """An exclusive ``flock`` on a private lock file; ``busy`` when another holder has it.
    A lock is held by an open file description, so a second process -- or a second open in
    this one -- is refused whatever directory it runs from."""
    try:
        descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                             dir_fd=directory)
    except OSError as exc:
        raise _refuse("private_storage_unavailable") from exc
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                _lock_now(descriptor)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _refuse(busy) from None
                time.sleep(0.05)
            except OSError as exc:
                raise _refuse("private_storage_unavailable") from exc
        yield
    finally:
        os.close(descriptor)


def _record_root(*, create: bool = True) -> int:
    from .president_adapter import private_record_root

    return _open_tree(private_record_root(), create=create)


# ------------------------------------------------------------------------------ grants

@dataclass(frozen=True)
class Grant:
    """``grant.json`` (§5.3): created once and bound to this host and one binary."""

    id: str
    host_digest: str
    binary_sha256: str
    planned: tuple[str, ...]
    retries: int
    cap: int
    budget: int
    created_at: str
    #: Erratum 4: the hosted CI run of the BA-3 egress check on the merged head
    #: (``GROK_HOSTED_CHECK_RUN``), recorded when the grant opens.
    hosted_check: str = ""

    def document(self) -> dict[str, Any]:
        return {"schema": GRANT_SCHEMA, "grant": self.id, "host_digest": self.host_digest,
                "binary_sha256": self.binary_sha256, "planned": list(self.planned),
                "retries": self.retries, "cap": self.cap, "budget": self.budget,
                "created_at": self.created_at, "hosted_check": self.hosted_check}


_GRANT_KEYS = frozenset({"schema", "grant", "host_digest", "binary_sha256", "planned", "retries",
                         "cap", "budget", "created_at", "hosted_check"})
#: A hosted run id or URL, as GROK_HOSTED_CHECK_RUN carries it.
_HOSTED_CHECK = re.compile(r"[A-Za-z0-9][A-Za-z0-9:/._?=&%#@+-]{0,255}")


def _check_grant_id(grant_id: object) -> str:
    if type(grant_id) is not str or _GRANT_ID.fullmatch(grant_id) is None:
        raise _refuse("grant_id_invalid")
    return grant_id


def _parse_grant(document: Mapping[str, Any], grant_id: str) -> Grant:
    _require(set(document) == _GRANT_KEYS and document["schema"] == GRANT_SCHEMA
             and document["grant"] == grant_id)
    planned = document["planned"]
    _require(type(planned) is list and bool(planned) and len(set(planned)) == len(planned)
             and all(route in MEASURED_ROUTES for route in planned))
    for key in ("retries", "cap", "budget"):
        _require(type(document[key]) is int and document[key] >= 0)
    _require(_hex64(document["host_digest"]) and _hex64(document["binary_sha256"])
             and type(document["created_at"]) is str
             and _UTC.fullmatch(document["created_at"]) is not None
             and type(document["hosted_check"]) is str
             and _HOSTED_CHECK.fullmatch(document["hosted_check"]) is not None)
    return Grant(id=grant_id, host_digest=document["host_digest"],
                 binary_sha256=document["binary_sha256"], planned=tuple(planned),
                 retries=document["retries"], cap=document["cap"], budget=document["budget"],
                 created_at=document["created_at"], hosted_check=document["hosted_check"])


def _grants_dir(*, create: bool) -> int:
    root = _record_root(create=create)
    try:
        return _subdir(root, GRANTS_DIRNAME, create=create)
    finally:
        os.close(root)


def new_grant(grant_id: str, *, binary_sha256: str, planned, retries: int,
              hosted_check: str | None) -> Grant:
    """Open a grant (``--new-grant``): ``grant.json`` is written once, exclusively, and
    every later stage must match it. Opening one spends nothing. Erratum 4: it records the
    hosted CI run of the BA-3 egress check (``--hosted-check``), which it requires."""
    from .seat_window import _host_digest

    _check_grant_id(grant_id)
    planned = tuple(planned)
    if (not planned or len(set(planned)) != len(planned)
            or not all(route in MEASURED_ROUTES for route in planned)):
        raise _refuse("planned_routes_invalid")
    if type(retries) is not int or not 0 <= retries <= GRANT_CAP:
        raise _refuse("retries_invalid")
    if type(hosted_check) is not str or _HOSTED_CHECK.fullmatch(hosted_check) is None:
        raise _refuse("hosted_check_required")
    grant = Grant(id=grant_id, host_digest=_host_digest(), binary_sha256=binary_sha256,
                  planned=planned, retries=retries, cap=GRANT_CAP, budget=PER_LAUNCH_BUDGET,
                  created_at=_utc_now(), hosted_check=hosted_check)
    grants = _grants_dir(create=True)
    try:
        try:
            os.mkdir(grant_id, 0o700, dir_fd=grants)
        except FileExistsError:
            raise _refuse("grant_exists") from None
        directory = _subdir(grants, grant_id, create=False)
        try:
            for name in ("reservations", "settlements", "results", "rehearsals"):
                os.close(_subdir(directory, name, create=True))
            _write_new(directory, "grant.json", grant.document())
        finally:
            os.close(directory)
    finally:
        os.close(grants)
    return grant


def _open_grant(grant_id: str, *, binary_sha256: str) -> tuple[int, Grant]:
    """The grant's directory and ``grant.json``, refused unless it binds this host, this
    binary and the plan's constants."""
    from .seat_window import _host_digest

    _check_grant_id(grant_id)
    try:
        grants = _grants_dir(create=False)
    except MeasurementRefused:
        raise _refuse("grant_unavailable") from None
    try:
        try:
            directory = _subdir(grants, grant_id, create=False)
        except MeasurementRefused:
            raise _refuse("grant_unavailable") from None
    finally:
        os.close(grants)
    try:
        try:
            grant = _parse_grant(_read_doc(directory, "grant.json"), grant_id)
        except (OSError, ValueError, TypeError, RecursionError):
            raise _refuse("grant_unavailable") from None
        if (grant.host_digest != _host_digest() or grant.binary_sha256 != binary_sha256
                or grant.cap != GRANT_CAP or grant.budget != PER_LAUNCH_BUDGET):
            raise _refuse("grant_mismatch")
    except BaseException:
        os.close(directory)
        raise
    return directory, grant


def other_grants_for_binary(grant: Grant) -> int:
    """How many other grants exist for the same host and binary (§5.3, the evidence)."""
    count = 0
    grants = _grants_dir(create=False)
    try:
        for name in sorted(os.listdir(grants)):
            if name == grant.id or _GRANT_ID.fullmatch(name) is None:
                continue
            try:
                directory = _subdir(grants, name, create=False)
            except MeasurementRefused:
                continue
            try:
                other = _parse_grant(_read_doc(directory, "grant.json"), name)
            except (OSError, ValueError, TypeError, RecursionError):
                continue
            finally:
                os.close(directory)
            if (other.host_digest, other.binary_sha256) == (grant.host_digest, grant.binary_sha256):
                count += 1
    finally:
        os.close(grants)
    return count


# ------------------------------------------------------------------------------ ledger

@dataclass(frozen=True)
class Reservation:
    id: str
    sequence: int
    route: str
    argv_digest: str
    budget: int
    at: str


@dataclass(frozen=True)
class Ledger:
    """What a grant has spent (§5.3). ``charged`` sums each reservation's settled count, or
    its whole budget where no settlement exists; an unreadable reservation is charged in full
    and counts as a launch."""

    grant: Grant
    reservations: tuple[Reservation, ...]
    unreadable: int
    last_sequence: int
    settlements: Mapping[str, int]
    #: Per reservation, its result records committed with the grant, by revision. They are
    #: the grant's one authoritative status, whatever output directory a stage runs from.
    results: Mapping[str, tuple[Mapping[str, Any], ...]]
    #: The sha256 of each committed record's bytes, by ``(reservation, revision)``.
    payloads: Mapping[tuple[str, int], str]
    unreadable_results: int
    #: Erratum 4: the grant's rehearsals, each a committed record, in sequence order.
    rehearsals: tuple[Mapping[str, Any], ...] = ()
    #: Rehearsal ids whose launch began: an attempt marker exists for each.
    rehearsal_attempts: tuple[str, ...] = ()

    def rehearsal_unresolved(self) -> tuple[str, ...]:
        """Rehearsals that launched and never committed a record: each is spent, and none
        passed (erratum 4)."""
        recorded = {item["rehearsal"] for item in self.rehearsals}
        return tuple(item for item in self.rehearsal_attempts if item not in recorded)

    def rehearsed(self, context: str, route: str | None = None) -> bool:
        """Erratum 4: has this grant a passing rehearsal of ``route`` (by default its pilot,
        the first planned route) for its binary and the context the code now enforces?"""
        route = self.grant.planned[0] if route is None else route
        return any(item["status"] == "passed" and item["context_digest"] == context
                   and item["binary_sha256"] == self.grant.binary_sha256
                   and item["route"] == route for item in self.rehearsals)

    def charged(self) -> int:
        return (sum(self.settlements.get(item.id, item.budget) for item in self.reservations)
                + self.unreadable * self.grant.budget)

    def launches(self) -> int:
        return len(self.reservations) + self.unreadable

    def retries_used(self) -> int:
        return self.launches() - len({item.route for item in self.reservations})

    def latest(self, route: str) -> Reservation | None:
        mine = [item for item in self.reservations if item.route == route]
        return mine[-1] if mine else None

    def latest_result(self, reservation: Reservation) -> Mapping[str, Any] | None:
        """The reservation's latest committed result: a revised record replaces the
        original only once it has committed."""
        results = self.results.get(reservation.id, ())
        return results[-1] if results else None

    def status(self, reservation: Reservation) -> str:
        """A reservation with no committed result is a failed attempt of its route
        (§5.7)."""
        result = self.latest_result(reservation)
        return "interrupted" if result is None else result["status"]

    def format_stop(self) -> bool:
        """§5.6: an unresolved ``format_unrecognised`` that is the latest for any route."""
        return any(self.status(latest) == "format_unrecognised"
                   for latest in (self.latest(route) for route in MEASURED_ROUTES)
                   if latest is not None)


_RESERVATION_KEYS = frozenset({"schema", "grant", "reservation", "sequence", "route",
                               "argv_digest", "budget", "binary_sha256", "host_digest", "at"})
_SETTLEMENT_KEYS = frozenset({"schema", "grant", "reservation", "settled", "requests", "at"})


def _read_ledger(directory: int, grant: Grant) -> Ledger:
    reservations: dict[int, Reservation] = {}
    unreadable = 0
    last = 0
    folder = _subdir(directory, "reservations", create=False)
    try:
        for name in sorted(os.listdir(folder)):
            match = _RESERVATION_NAME.fullmatch(name)
            if match is not None:
                last = max(last, int(match.group(1)))
            try:
                _require(match is not None)
                assert match is not None
                document = _read_doc(folder, name)
                _require(set(document) == _RESERVATION_KEYS
                         and document["schema"] == RESERVATION_SCHEMA
                         and document["grant"] == grant.id
                         and document["reservation"] == name[:-len(".json")]
                         and document["sequence"] == int(match.group(1))
                         and document["route"] in grant.planned
                         and _hex64(document["argv_digest"])
                         and document["budget"] == grant.budget
                         and document["binary_sha256"] == grant.binary_sha256
                         and document["host_digest"] == grant.host_digest
                         and type(document["at"]) is str
                         and _UTC.fullmatch(document["at"]) is not None
                         and document["sequence"] not in reservations)
            except (OSError, ValueError, TypeError, RecursionError, KeyError):
                unreadable += 1
                continue
            reservations[document["sequence"]] = Reservation(
                id=document["reservation"], sequence=document["sequence"],
                route=document["route"], argv_digest=document["argv_digest"],
                budget=document["budget"], at=document["at"])
    finally:
        os.close(folder)
    by_id = {item.id: item for item in reservations.values()}
    settlements: dict[str, int] = {}
    folder = _subdir(directory, "settlements", create=False)
    try:
        for name in sorted(os.listdir(folder)):
            reservation = by_id.get(name[:-len(".json")]) if name.endswith(".json") else None
            try:
                _require(reservation is not None)
                assert reservation is not None
                document = _read_doc(folder, name)
                _require(set(document) == _SETTLEMENT_KEYS
                         and document["schema"] == SETTLEMENT_SCHEMA
                         and document["grant"] == grant.id
                         and document["reservation"] == reservation.id
                         and type(document["settled"]) is int
                         and 0 <= document["settled"] <= reservation.budget)
            except (OSError, ValueError, TypeError, RecursionError, KeyError):
                continue  # no usable settlement: the reservation stays charged in full
            settlements[reservation.id] = document["settled"]
    finally:
        os.close(folder)
    results: dict[str, list[Mapping[str, Any]]] = {}
    payloads: dict[tuple[str, int], str] = {}
    unreadable_results = 0
    folder = _subdir(directory, "results", create=False)
    try:
        for name in sorted(os.listdir(folder)):
            if name.startswith("."):
                continue  # a commit's temp file: never a record
            match = _COMMITTED_NAME.fullmatch(name)
            try:
                _require(match is not None)
                assert match is not None
                reservation = by_id.get(match.group(1))
                raw = _read_file(folder, name, _RECORD_MAX_BYTES)
                document = _loads(raw)
                _require(type(document) is dict and reservation is not None)
                assert isinstance(document, dict) and reservation is not None
                check_result_keys(document)
                _require(document["schema"] == RESULT_SCHEMA and document["grant"] == grant.id
                         and document["reservation"] == reservation.id
                         and document["route"] == reservation.route
                         and document["argv_digest"] == reservation.argv_digest
                         and document["revision"] == int(match.group(2)))
            except (OSError, ValueError, TypeError, RecursionError, KeyError):
                unreadable_results += 1
                continue
            results.setdefault(reservation.id, []).append(document)
            payloads[(reservation.id, document["revision"])] = sha256(raw).hexdigest()
    finally:
        os.close(folder)
    return Ledger(grant=grant, reservations=tuple(reservations[key] for key in sorted(reservations)),
                  unreadable=unreadable, last_sequence=last, settlements=settlements,
                  results={key: tuple(sorted(value, key=lambda item: item["revision"]))
                           for key, value in results.items()},
                  payloads=payloads, unreadable_results=unreadable_results,
                  rehearsals=_read_rehearsals(directory, grant),
                  rehearsal_attempts=_read_rehearsal_attempts(directory))


_REHEARSAL_NAME = re.compile(r"(\d{4})-([0-9a-f]{16})\.json")
#: Erratum 4: written at the launch boundary, before the credentialed child can start.
_ATTEMPT_NAME = re.compile(r"(\d{4})-([0-9a-f]{16})\.attempt\.json")
REHEARSAL_ATTEMPT_SCHEMA = "grok_tool_surface_rehearsal_attempt.v1"
REHEARSAL_KEYS = frozenset({"schema", "grant", "rehearsal", "route", "argv_digest",
                            "binary_sha256", "context_digest", "egress", "status", "reason",
                            "exit_code", "observation", "incomplete", "budget_denials",
                            "tolerated_refusals", "observed", "at"})
_OBSERVED_KEYS = frozenset({"method", "host", "path", "decision"})
_OBSERVED_CAP = 256
#: What an ``observation_incomplete`` rehearsal records about what was missing: the first
#: unmet condition of BA-1's completion proof (``missing``) and the proxy's own metadata,
#: :func:`seat_egress_proxy.completion_detail`. ``None`` on every other rehearsal.
_INCOMPLETE_KEYS = frozenset({"missing", "marker", "last_record", "records", "exit_status",
                              "killed", "stdout_eof", "exited", "protocol_error"})
_INCOMPLETE_FLAGS = ("marker", "killed", "stdout_eof", "exited", "protocol_error")


def check_rehearsal_keys(document: Mapping[str, Any]) -> None:
    _require(set(document) == REHEARSAL_KEYS and set(document["egress"]) == _EGRESS_KEYS
             and set(document["observation"]) == _OBSERVATION_KEYS
             and document["status"] in ("passed", "failed")
             and document["reason"] in REHEARSAL_REASONS
             and (document["status"] == "passed") == (document["reason"] == "passed"))
    incomplete = document["incomplete"]
    _require((incomplete is None) == (document["reason"] != "observation_incomplete"))
    if incomplete is not None:
        _require(type(incomplete) is dict and set(incomplete) == _INCOMPLETE_KEYS
                 and type(incomplete["missing"]) is str
                 and _KEY_NAME.fullmatch(incomplete["missing"]) is not None
                 and incomplete["last_record"] in (None, "request", "fence", "end")
                 and all(incomplete[name] is None or type(incomplete[name]) is bool
                         for name in _INCOMPLETE_FLAGS)
                 and all(incomplete[name] is None or type(incomplete[name]) is int
                         for name in ("records", "exit_status")))
    _check_tolerated(document["tolerated_refusals"])
    observed = document["observed"]
    _require(type(observed) is list and len(observed) <= _OBSERVED_CAP
             and all(type(item) is dict and set(item) == _OBSERVED_KEYS for item in observed))


def _read_rehearsal_attempts(directory: int) -> tuple[str, ...]:
    """The ids of every rehearsal whose launch began, from its marker's name alone: a marker
    that cannot be read still spends the grant's one rehearsal."""
    try:
        folder = _subdir(directory, "rehearsals", create=False)
    except MeasurementRefused:
        return ()
    try:
        return tuple(sorted(match.group(1) + "-" + match.group(2) for name in os.listdir(folder)
                            if (match := _ATTEMPT_NAME.fullmatch(name))))
    finally:
        os.close(folder)


def _read_rehearsals(directory: int, grant: Grant) -> tuple[Mapping[str, Any], ...]:
    """The grant's committed rehearsal records; one that cannot be read is no rehearsal."""
    rehearsals = []
    try:
        folder = _subdir(directory, "rehearsals", create=False)
    except MeasurementRefused:
        return ()
    try:
        for name in sorted(os.listdir(folder)):
            if name.startswith(".") or _REHEARSAL_NAME.fullmatch(name) is None:
                continue
            try:
                document = _read_doc(folder, name)
                check_rehearsal_keys(document)
                _require(document["schema"] == REHEARSAL_SCHEMA and document["grant"] == grant.id
                         and document["rehearsal"] == name[:-len(".json")])
            except (OSError, ValueError, TypeError, RecursionError, KeyError):
                continue
            rehearsals.append(document)
    finally:
        os.close(folder)
    return tuple(rehearsals)


def _plan_reservation(ledger: Ledger, route: str, argv_digest: str, context: str) -> Reservation:
    """The next reservation of ``route``, checked against every grant limit (§5.3) but not
    yet written. The caller holds the grant lock. Erratum 4: no reservation without a
    passing rehearsal in this grant under the context the code now enforces."""
    grant = ledger.grant
    if route not in grant.planned:
        raise _refuse("route_not_planned")
    # Erratum 4: no reservation without the grant's passing rehearsal of its pilot (the
    # pilot's own route) for this binary and the context the code now enforces.
    if not ledger.rehearsed(context):
        raise _refuse("rehearsal_required")
    if ledger.format_stop():
        raise _refuse("format_unrecognised_unresolved")
    # A launch of a route already launched is a retry; an unreadable reservation counts as
    # one. Both limits hold: the retry allowance and planned routes plus that allowance.
    retries = ledger.retries_used() + (route in {item.route for item in ledger.reservations})
    if retries > grant.retries or ledger.launches() + 1 > len(grant.planned) + grant.retries:
        raise _refuse("grant_retries_exhausted")
    if ledger.charged() + grant.budget > grant.cap:
        raise _refuse("grant_cap_reached")
    sequence = ledger.last_sequence + 1
    if sequence > 9999:
        raise _refuse("grant_retries_exhausted")
    return Reservation(id=f"{sequence:04d}-{secrets.token_hex(8)}", sequence=sequence,
                       route=route, argv_digest=argv_digest, budget=grant.budget, at=_utc_now())


def _write_reservation(directory: int, grant: Grant, reservation: Reservation) -> None:
    """Reserve one launch's whole budget, immutably (``O_EXCL``, file and directory
    fsynced), before its proxy exists (§5.3). A crash mid-write leaves a reservation that
    cannot be read, which is charged in full and counts as a launch."""
    sequence, route, argv_digest = reservation.sequence, reservation.route, reservation.argv_digest
    folder = _subdir(directory, "reservations", create=False)
    try:
        _write_new(folder, reservation.id + ".json", {
            "schema": RESERVATION_SCHEMA, "grant": grant.id, "reservation": reservation.id,
            "sequence": sequence, "route": route, "argv_digest": argv_digest,
            "budget": grant.budget, "binary_sha256": grant.binary_sha256,
            "host_digest": grant.host_digest, "at": reservation.at})
    except OSError as exc:
        raise _refuse("private_storage_unavailable") from exc
    finally:
        os.close(folder)


def _settle(directory: int, grant: Grant, reservation: Reservation, proxy: Any) -> int | None:
    """Reconcile after the proxy has exited, on positive proof only (§5.3, BA-1): a
    settlement is written only when L2a's completion proof holds -- a clean requested exit,
    the end-of-stream marker as the last record with a count equal to the records read, and
    no protocol error. Otherwise nothing is written and the reservation stays charged in
    full, permanently. Returns the settled count, or ``None``."""
    from . import seat_egress_proxy

    if proxy is None or proxy.request_budget != reservation.budget:
        return None
    proof = seat_egress_proxy.completion(proxy)
    if not proof.complete or not 0 <= proof.counted <= reservation.budget:
        return None
    folder = _subdir(directory, "settlements", create=False)
    try:
        _write_new(folder, reservation.id + ".json", {
            "schema": SETTLEMENT_SCHEMA, "grant": grant.id, "reservation": reservation.id,
            "settled": proof.counted, "requests": proof.requests, "at": _utc_now()})
    except OSError:
        return None
    finally:
        os.close(folder)
    return proof.counted


# ---------------------------------------------------- the attempts register (§5.7, BA-2)

def attempts_name(binary_sha256: str) -> str:
    return "grok-surface-" + binary_sha256 + ".attempts.json"


def publication_lock_name(binary_sha256: str) -> str:
    return "grok-surface-" + binary_sha256 + ".lock"


@contextlib.contextmanager
def _publication(binary_sha256: str) -> Iterator[int]:
    """The per-binary publication lock in the private record root (§5.7): every writer of
    one binary's host-local record and attempts register takes it, whatever grant or output
    directory it runs from."""
    root = _record_root(create=True)
    try:
        with _flock(root, publication_lock_name(binary_sha256), busy="publication_busy",
                    wait_s=PUBLICATION_WAIT_S):
            yield root
    finally:
        os.close(root)


@dataclass(frozen=True)
class Register:
    """``grok-surface-<binary>.attempts.json`` (§5.7, BA-2), per argv digest: ``attempts``,
    the latest attempt by any grant; ``published``, the reservation and record route a
    host-local route was published from. A host-local route is consumable only while its
    ``published`` entry names the latest attempt and the route's own digest."""

    attempts: Mapping[str, Mapping[str, str]]
    published: Mapping[str, Mapping[str, str]]


_ATTEMPT_KEYS = frozenset({"route", "grant", "reservation", "at"})
_PUBLISHED_KEYS = frozenset({"grant", "reservation", "surface_digest"})


def _read_register(root: int, binary_sha256: str) -> Register | None:
    """The register; empty when there is none yet and ``None`` when it cannot be read
    (which publishes nothing and makes no host-local route consumable)."""
    from .seat_window import _host_digest

    try:
        document = _read_doc(root, attempts_name(binary_sha256))
    except FileNotFoundError:
        return Register(attempts={}, published={})
    except (OSError, ValueError, TypeError, RecursionError):
        return None
    try:
        _require(set(document) == {"schema", "binary_sha256", "host_digest", "attempts",
                                   "published"}
                 and document["schema"] == ATTEMPTS_SCHEMA
                 and document["binary_sha256"] == binary_sha256
                 and document["host_digest"] == _host_digest()
                 and type(document["attempts"]) is dict and type(document["published"]) is dict)
        for table, keys in ((document["attempts"], _ATTEMPT_KEYS),
                            (document["published"], _PUBLISHED_KEYS)):
            for digest, entry in table.items():
                _require(_hex64(digest) and type(entry) is dict and set(entry) == keys
                         and all(type(value) is str for value in entry.values()))
    except (ValueError, TypeError):
        return None
    return Register(attempts=document["attempts"], published=document["published"])


def _write_register(root: int, binary_sha256: str, register: Register) -> None:
    from .seat_window import _host_digest

    _replace_file(root, attempts_name(binary_sha256), {
        "schema": ATTEMPTS_SCHEMA, "binary_sha256": binary_sha256,
        "host_digest": _host_digest(), "attempts": dict(register.attempts),
        "published": dict(register.published)})


def host_route_current(binary_sha256: str, argv_digest: str, route_digest: str) -> bool:
    """May the host-local route for ``(binary_sha256, argv_digest)``, whose
    :func:`surface_digest` is ``route_digest``, be consumed (§5.7, BA-2)? Only while the
    register names it published from the latest attempt by any grant. A newer attempt is
    registered -- and ``published`` cleared -- before its reservation exists, so from the
    moment one can exist the prior pass stops admitting, whichever step a crash interrupts.
    A missing or unreadable register admits nothing. The shipped catalog is not consulted
    here: its routes keep their precedence (§3.2)."""
    try:
        root = _record_root(create=False)
    except MeasurementRefused:
        return False
    try:
        register = _read_register(root, binary_sha256)
    finally:
        os.close(root)
    if register is None:
        return False
    published = register.published.get(argv_digest)
    latest = register.attempts.get(argv_digest)
    return (published is not None and latest is not None
            and published["grant"] == latest["grant"]
            and published["reservation"] == latest["reservation"]
            and published["surface_digest"] == route_digest)


def _host_record_document(root: int, binary_sha256: str) -> dict | None:
    from .seat_window import _host_digest

    raw = _read_file(root, host_record_name(binary_sha256), HOST_RECORD_MAX_BYTES)
    document = _loads(raw)
    _require(type(document) is dict and set(document) == {"schema", "host_digest", "surface"})
    assert isinstance(document, dict)
    _require(document["schema"] == HOST_RECORD_SCHEMA and document["host_digest"] == _host_digest())
    _check_surface(document["surface"])
    _require(document["surface"]["binary_sha256"] == binary_sha256)
    return document


def _remove_host_record(root: int, binary_sha256: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(host_record_name(binary_sha256), dir_fd=root)


def _withdraw(root: int, binary_sha256: str, argv_digest: str) -> None:
    """Withdraw before launching (§5.7): route ``argv_digest`` leaves the host-local record,
    or the record goes when it was the last route. A record that cannot be read goes too."""
    from .president_adapter import private_record_root, write_private_record

    try:
        document = _host_record_document(root, binary_sha256)
    except FileNotFoundError:
        return
    except (OSError, ValueError, TypeError, RecursionError):
        _remove_host_record(root, binary_sha256)
        return
    assert document is not None
    surface = document["surface"]
    routes = [route for route in surface["routes"] if route["argv_digest"] != argv_digest]
    if routes == surface["routes"]:
        return
    _remove_host_record(root, binary_sha256)
    if routes:
        write_private_record(host_record_name(binary_sha256),
                             {**document, "surface": {**surface, "routes": routes}},
                             root=private_record_root())


def _record_attempt(root: int, grant: Grant, reservation: Reservation) -> None:
    """Name ``reservation`` the latest attempt of its route and clear the route's
    publication (§5.7). Written, durably, before the route is withdrawn and before the
    reservation exists; an unreadable register is started afresh, which consumes nothing."""
    register = _read_register(root, grant.binary_sha256) or Register(attempts={}, published={})
    attempts = dict(register.attempts)
    attempts[reservation.argv_digest] = {"route": reservation.route, "grant": grant.id,
                                         "reservation": reservation.id, "at": reservation.at}
    published = {key: value for key, value in register.published.items()
                 if key != reservation.argv_digest}
    _write_register(root, grant.binary_sha256, Register(attempts=attempts, published=published))


# ------------------------------------------------------------ the measurement admission

@dataclass(frozen=True)
class MeasurementAdmission:
    """§5.1: the one admission a receipt-less grok argv can have. It is issued only by
    :func:`_measure_route`, for one argv form, one measured binary and the one budgeted proxy
    and namespace that launch owns, and is held in a context variable for that launch alone;
    never from argv or the environment."""

    argv_digest: str
    binary_sha256: str
    egress_prefix: tuple[str, ...]
    proxy: object = field(repr=False, compare=False)
    issuer: object = field(default=None, repr=False, compare=False)
    #: The budget of the proxy this launch owns: one counted request for a measurement,
    #: none for a rehearsal (erratum 4).
    request_budget: int = PER_LAUNCH_BUDGET

    def __post_init__(self) -> None:
        if self.issuer is not _ISSUER:
            raise TypeError("a measurement admission is issued only by the measurement")
        if self.request_budget not in (0, PER_LAUNCH_BUDGET):
            raise TypeError("a measurement admission carries budget 1, or 0 to rehearse")


_MEASUREMENT_ADMISSION: ContextVar[MeasurementAdmission | None] = ContextVar(
    "grok_measurement_admission", default=None)


def measurement_admission() -> MeasurementAdmission | None:
    """The measurement admission held by this context, if any."""
    return _MEASUREMENT_ADMISSION.get()


@contextlib.contextmanager
def _holding(admission: MeasurementAdmission) -> Iterator[None]:
    token = _MEASUREMENT_ADMISSION.set(admission)
    try:
        yield
    finally:
        _MEASUREMENT_ADMISSION.reset(token)


def measurement_admits(admission: object, argv, env) -> bool:
    """Does ``admission`` admit ``argv`` (``panel_invoker.require_grok_admission``)? Only
    for its own argv form and binary, while its own budgeted ``grok-review`` proxy is alive
    and the launch's egress prefix is exactly the namespace bridged to that proxy."""
    from . import panel_invoker as panel
    from .seat_egress_proxy import SeatEgressProxy

    try:
        if not (isinstance(admission, MeasurementAdmission) and admission.issuer is _ISSUER):
            return False
        proxy = admission.proxy
        if not (isinstance(proxy, SeatEgressProxy) and proxy.allowlist_id == EGRESS_ALLOWLIST_ID
                and proxy.allowlist_digest == egress_allowlist_digest()
                and proxy.request_budget == admission.request_budget
                and admission.request_budget in (0, PER_LAUNCH_BUDGET)
                and bool(proxy.socket) and proxy.process.poll() is None):
            return False
        prefix = tuple(panel._EGRESS_LAUNCH_PREFIX.get())
        if not admission.egress_prefix or prefix != admission.egress_prefix:
            return False
        panel._filtered_holder_namespace()
        if not bridged_to(prefix, proxy):
            return False
        return (panel._grok_argv_digest(list(argv)) == admission.argv_digest
                and panel._grok_binary_identity(list(argv), env)[1] == admission.binary_sha256)
    except Exception:  # noqa: BLE001 - any doubt refuses
        return False


# ------------------------------------------------------------ reading the artifact (§5.5)

class ArtifactRefused(ValueError):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def read_definitions(sessions: int) -> bytes:
    """The one ``<group>/<session>/tool_definitions.json`` under the scratch sessions
    directory ``sessions`` (an open descriptor). Every component is opened relative to its
    parent without following a link; the file must be a regular file of the launch's mapped
    uid, at most 4 MiB, read through its descriptor with a bound. Zero candidates is
    ``artifact_missing``; several, a link, another file type, an over-size or foreign file
    is ``artifact_ambiguous``."""

    def entries(directory: int) -> list[str]:
        names = []
        for name in sorted(os.listdir(directory)):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ArtifactRefused("artifact_ambiguous")
            if stat.S_ISDIR(info.st_mode):
                names.append(name)
        return names

    candidates: list[tuple[str, str]] = []
    try:
        for group in entries(sessions):
            group_fd = os.open(group, _dir_flags(), dir_fd=sessions)
            try:
                for session in entries(group_fd):
                    session_fd = os.open(session, _dir_flags(), dir_fd=group_fd)
                    try:
                        try:
                            info = os.stat(DEFINITIONS_NAME, dir_fd=session_fd,
                                           follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            raise ArtifactRefused("artifact_ambiguous")
                        candidates.append((group, session))
                    finally:
                        os.close(session_fd)
            finally:
                os.close(group_fd)
        if not candidates:
            raise ArtifactRefused("artifact_missing")
        if len(candidates) > 1:
            raise ArtifactRefused("artifact_ambiguous")
        group, session = candidates[0]
        group_fd = os.open(group, _dir_flags(), dir_fd=sessions)
        try:
            session_fd = os.open(session, _dir_flags(), dir_fd=group_fd)
            try:
                descriptor = os.open(DEFINITIONS_NAME,
                                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                     dir_fd=session_fd)
            finally:
                os.close(session_fd)
        finally:
            os.close(group_fd)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_size > DEFINITIONS_MAX_BYTES):
                raise ArtifactRefused("artifact_ambiguous")
            raw = _read_bounded(descriptor, DEFINITIONS_MAX_BYTES)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ArtifactRefused("artifact_ambiguous") from exc
    if len(raw) > DEFINITIONS_MAX_BYTES:
        raise ArtifactRefused("artifact_ambiguous")
    return raw


# --------------------------------------------------------------- extracting names (§5.6)

class FormatUnrecognised(ValueError):
    """The artifact is not S1, S2 or S3, or names a tool outside the §3.1 pattern.
    ``structure`` is its sanitized structure (§5.6, §5.9)."""

    def __init__(self, structure: Mapping[str, Any]) -> None:
        super().__init__("format_unrecognised")
        self.structure = structure


def sanitized_structure(document: object) -> dict[str, Any]:
    """JSON types and key names to depth 3, no string value. A key name is exported only if
    it matches ``[A-Za-z0-9_]{1,64}``, otherwise as ``#<its length>``; at most 64 keys per
    object and the first four items of an array, within a fixed node bound."""
    nodes = [_STRUCTURE_NODES]

    def kind(value: object) -> str:
        if value is None:
            return "null"
        if type(value) is bool:
            return "boolean"
        if type(value) in (int, float):
            return "number"
        if type(value) is str:
            return "string"
        if type(value) is list:
            return "array"
        return "object"

    def walk(value: object, depth: int) -> dict[str, Any]:
        if nodes[0] <= 0:
            return {"type": "truncated"}
        nodes[0] -= 1
        name = kind(value)
        if name == "object":
            assert isinstance(value, dict)
            node: dict[str, Any] = {"type": "object", "size": len(value)}
            if depth < 3:
                node["keys"] = [
                    [key if type(key) is str and _KEY_NAME.fullmatch(key) else f"#{len(key)}",
                     walk(item, depth + 1)]
                    for key, item in list(value.items())[:64]]
            return node
        if name == "array":
            assert isinstance(value, list)
            node = {"type": "array", "length": len(value)}
            if depth < 3:
                node["items"] = [walk(item, depth + 1) for item in value[:4]]
            return node
        return {"type": name}

    return walk(document, 0)


def extract_tool_names(raw: bytes) -> tuple[str, list[str]]:
    """``(shape, tools)`` for an artifact of one recognised shape (§5.6): **S1** an array
    of objects each with a string ``name``; **S2** an array of objects each with a string
    ``function.name``; **S3** an object whose ``tools`` is S1 or S2. Mixed arrays, a missing
    name, a shape with more than one reading, or a name outside ``[A-Za-z0-9_.-]{1,96}``
    raise :class:`FormatUnrecognised`; the extractor never guesses. An empty array has one
    reading, the empty set, and is recorded as shape ``empty``."""
    try:
        document = _loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise FormatUnrecognised({"type": "unparseable"}) from None

    def reading(items: object) -> tuple[str, list[str]] | None:
        if type(items) is not list:
            return None
        assert isinstance(items, list)
        if not items:
            return "empty", []
        s1 = all(type(item) is dict and type(item.get("name")) is str for item in items)
        s2 = all(type(item) is dict and type(item.get("function")) is dict
                 and type(item["function"].get("name")) is str for item in items)
        if s1 == s2:
            return None
        return ("S1", [item["name"] for item in items]) if s1 else (
            "S2", [item["function"]["name"] for item in items])

    if type(document) is list:
        result = reading(document)
    elif type(document) is dict and "tools" in document:
        assert isinstance(document, dict)
        inner = reading(document["tools"])
        result = None if inner is None else ("S3", inner[1])
    else:
        result = None
    if result is None or not all(_TOOL.fullmatch(name) for name in result[1]):
        raise FormatUnrecognised(sanitized_structure(document))
    return result[0], sorted(set(result[1]))


# ---------------------------------------------------------- records and their key lists

_EGRESS_KEYS = frozenset({"allowlist_id", "allowlist_sha256"})
_OBSERVATION_KEYS = frozenset({"complete", "reason", "requests", "counted", "denied"})
_STRUCTURE_KEYS = frozenset({"type", "size", "keys", "length", "items"})
#: §5.9: the key allow-list the result writer enforces. Names, digests, counts, statuses.
RESULT_KEYS = frozenset({
    "schema", "grant", "reservation", "route", "argv_digest", "binary_sha256", "version",
    "version_sha256", "help_sha256", "model", "effort", "context", "context_digest",
    "host_digest", "runtime_digest", "egress", "prompt_sha256", "status", "eligible",
    "admitted", "shape", "tools", "definitions_sha256", "definitions_bytes", "exit_code",
    "observation", "tolerated_refusals", "structure", "reprocessed_from", "revision",
    "extractor", "at"})
#: §5.8 and §5.9: the aggregate's key allow-list.
EVIDENCE_KEYS = frozenset({
    "schema", "binary_sha256", "version", "version_sha256", "help_sha256", "host_class",
    "host_digest", "runtime_digest", "context", "context_digest", "account_scope", "method",
    "model", "effort", "egress", "prompt_sha256", "grant", "reservations", "routes"})
_EVIDENCE_GRANT_KEYS = frozenset({"id", "planned", "retries", "cap", "charged",
                                  "other_grants_for_binary"})
_EVIDENCE_RESERVATION_KEYS = frozenset({"id", "at", "route", "budget", "settled", "reprocessed"})
_EVIDENCE_ROUTE_KEYS = frozenset({"route", "argv_digest", "status", "eligible", "shape", "tools",
                                  "definitions_sha256", "definitions_bytes", "reservation",
                                  "exit_code", "admitted", "superseded", "tolerated_refusals"})
_TOLERATED_KEYS = frozenset({"method", "host", "path", "count"})


def _check_tolerated(entries: object) -> None:
    _require(type(entries) is list)
    assert isinstance(entries, list)
    for entry in entries:
        _require(type(entry) is dict and set(entry) == _TOLERATED_KEYS
                 and (entry["method"], entry["host"], entry["path"]) in TOLERATED_REFUSALS
                 and type(entry["count"]) is int and entry["count"] > 0)


def tolerated_summary(events) -> list[dict[str, Any]]:
    """The tolerated refusals of erratum 3 among ``events``: each entry and its count,
    metadata only."""
    counts: dict[tuple, int] = {}
    for event in events:
        key = (event.method, event.host, event.path)
        if event.decision == "deny" and key in TOLERATED_REFUSALS:
            counts[key] = counts.get(key, 0) + 1
    return [{"method": key[0], "host": key[1], "path": key[2], "count": counts[key]}
            for key in TOLERATED_REFUSALS if key in counts]


def _check_structure(node: object) -> None:
    _require(type(node) is dict and set(node) <= _STRUCTURE_KEYS)
    assert isinstance(node, dict)
    for pair in node.get("keys", ()):
        _require(type(pair) is list and len(pair) == 2 and type(pair[0]) is str
                 and (_KEY_NAME.fullmatch(pair[0]) or re.fullmatch(r"#\d{1,6}", pair[0])))
        _check_structure(pair[1])
    for item in node.get("items", ()):
        _check_structure(item)


def check_result_keys(document: Mapping[str, Any]) -> None:
    """The result writer's allow-list (§5.9); :class:`_Refused` on any other key."""
    _require(set(document) == RESULT_KEYS)
    _require(set(document["egress"]) == _EGRESS_KEYS)
    _require(set(document["observation"]) == _OBSERVATION_KEYS)
    _require(document["status"] in STATUSES)
    _check_tolerated(document["tolerated_refusals"])
    if document["structure"] is not None:
        _check_structure(document["structure"])
    tools = document["tools"]
    _require(tools is None or (type(tools) is list and all(type(t) is str and _TOOL.fullmatch(t)
                                                          for t in tools)))


def check_evidence_keys(document: Mapping[str, Any]) -> None:
    """The aggregate writer's allow-list (§5.8, §5.9)."""
    _require(set(document) == EVIDENCE_KEYS and set(document["egress"]) == _EGRESS_KEYS
             and set(document["grant"]) == _EVIDENCE_GRANT_KEYS)
    for item in document["reservations"]:
        _require(set(item) == _EVIDENCE_RESERVATION_KEYS)
    for item in document["routes"]:
        _require(set(item) == _EVIDENCE_ROUTE_KEYS and item["status"] in STATUSES)
        _check_tolerated(item["tolerated_refusals"])
        _require(item["tools"] is None or all(_TOOL.fullmatch(t) for t in item["tools"]))


# ------------------------------------------------------------------ output and retention

def _open_output(output: str | os.PathLike | None) -> tuple[int, Path]:
    """``--output``: a private directory under the operator's private state home, never in
    a git work tree (§5.9). Only ``tool-surface.json`` ever leaves the host."""
    from .seat_jail import state_home

    if not output:
        raise _refuse("output_required")
    path = Path(os.path.realpath(output))
    home = Path(os.path.realpath(state_home()))
    if path == home or home not in path.parents:
        raise _refuse("output_outside_private_state")
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise _refuse("output_inside_work_tree")
    descriptor = _open_tree(path, create=True)
    try:
        for name in ("results", "raw"):
            os.close(_subdir(descriptor, name, create=True))
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, path


def _retain(directory: int, name: str, data: bytes, retention_s: int) -> None:
    """A retained private file and its operative deadline, written with it (§5.9). The
    deadline is written first, so no retained file exists without one."""
    _write_new(directory, name + ".expires_at", f"{int(time.time()) + retention_s}\n".encode())
    _write_new(directory, name, data)


def sweep_expired(output: int, *, now: float | None = None) -> int:
    """Delete what has expired under the output directory and return the count (§5.9). A
    retained file with no readable deadline counts as expired. Raises on a failed deletion."""
    now = time.time() if now is None else now
    removed = 0
    # A launch's scratch directory is removed in ``finally``; one a killed run left behind
    # (it may hold a session transcript) goes once no launch could still be using it.
    for name in sorted(os.listdir(output)):
        if name.startswith("scratch-"):
            info = os.stat(name, dir_fd=output, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode) and info.st_mtime < now - (LAUNCH_TIMEOUT_S + 3600):
                shutil.rmtree(name, dir_fd=output)
                removed += 1
    results = _subdir(output, "results", create=True)
    try:
        _remove_commit_temps(results, older_than_s=LAUNCH_TIMEOUT_S + 3600)
    finally:
        os.close(results)
    raw = _subdir(output, "raw", create=True)
    try:
        for reservation in sorted(os.listdir(raw)):
            folder = _subdir(raw, reservation, create=False)
            try:
                names = set(os.listdir(folder))
                for name in sorted(names):
                    if name.endswith(".expires_at"):
                        continue
                    deadline = None
                    if name + ".expires_at" in names:
                        with contextlib.suppress(OSError, ValueError, TypeError):
                            deadline = int(_read_file(folder, name + ".expires_at", 64))
                    if deadline is None or deadline <= now:
                        os.unlink(name, dir_fd=folder)
                        with contextlib.suppress(FileNotFoundError):
                            os.unlink(name + ".expires_at", dir_fd=folder)
                        removed += 1
                for name in sorted(names):
                    stem = name[:-len(".expires_at")]
                    if name.endswith(".expires_at") and stem not in os.listdir(folder):
                        with contextlib.suppress(FileNotFoundError):
                            os.unlink(name, dir_fd=folder)
                empty = not os.listdir(folder)
            finally:
                os.close(folder)
            if empty:
                os.rmdir(reservation, dir_fd=raw)
    finally:
        os.close(raw)
    return removed


#: The lock file a launch holds in its scratch directory for as long as the launch runs.
SCRATCH_LOCK = ".active"


def _new_scratch(output_path) -> tuple[Path, int]:
    """A launch's private scratch directory and the exclusive lock marking it active (§5.9).
    The lock is taken before anything is written into the directory and is held until the
    launch's own cleanup (:func:`_drop_scratch`); a killed process releases it, so
    ``--purge`` can tell an abandoned scratch directory from a live one."""
    scratch = Path(tempfile.mkdtemp(prefix="scratch-", dir=output_path))
    try:
        lock = os.open(scratch / SCRATCH_LOCK,
                       os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            _lock_now(lock)
        except BaseException:
            os.close(lock)
            raise
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return scratch, lock


def _drop_scratch(scratch: Path, lock: int) -> None:
    try:
        shutil.rmtree(scratch, ignore_errors=True)
    finally:
        os.close(lock)


def purge_scratch(output: int) -> dict[str, Any]:
    """``--purge`` for launch scratch directories, which may hold session transcripts and the
    prompt (§5.9). A scratch directory goes at once when its lock can be taken: no launch is
    using it, as a killed one released the lock. A held lock is a live launch, whose own
    cleanup removes it, so it is left and reported. A directory whose lock cannot be read
    cannot be judged, so it is left and reported too: purge fails closed rather than
    reporting a cleanup it did not do."""
    removed, active, unknown = 0, [], []
    for name in sorted(os.listdir(output)):
        if not name.startswith("scratch-"):
            continue
        try:
            folder = os.open(name, _dir_flags(), dir_fd=output)
        except OSError:
            unknown.append(name)
            continue
        try:
            try:
                lock = os.open(SCRATCH_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                               dir_fd=folder)
            except OSError:
                unknown.append(name)
                continue
            try:
                try:
                    _lock_now(lock)
                except BlockingIOError:
                    active.append(name)
                    continue
                except OSError:
                    unknown.append(name)  # no lock can be judged here: fail closed
                    continue
                shutil.rmtree(name, dir_fd=output)  # while holding its lock
                removed += 1
            finally:
                os.close(lock)
        finally:
            os.close(folder)
    return {"scratch_removed": removed, "scratch_active": active, "scratch_unknown": unknown}


def purge(output: int) -> int:
    """``--purge``: everything retained goes at once (§5.9); results and the aggregate,
    which hold names and digests only, stay. Returns the count of files deleted. Launch
    scratch directories are :func:`purge_scratch`'s."""
    removed = 0
    raw = _subdir(output, "raw", create=True)
    try:
        for reservation in sorted(os.listdir(raw)):
            folder = _subdir(raw, reservation, create=False)
            try:
                for name in sorted(os.listdir(folder)):
                    os.unlink(name, dir_fd=folder)
                    removed += 0 if name.endswith(".expires_at") else 1
            finally:
                os.close(folder)
            os.rmdir(reservation, dir_fd=raw)
    finally:
        os.close(raw)
    return removed


# -------------------------------------------------------------- the launch (§5.1, §5.4)

def _measure_binary(binary: str | None, expected: str | None) -> tuple[str, str, tuple]:
    """``--binary`` measured against ``--expect-binary-sha256`` before anything is
    projected; it must be named ``grok`` so the shared launch gate governs it."""
    from . import panel_invoker as panel

    if not _hex64(expected):
        raise _refuse("expected_digest_invalid")
    if not binary or not os.path.isabs(binary) or Path(binary).name != "grok":
        raise _refuse("binary_unavailable")
    try:
        identity = panel._grok_probe_identity([binary], panel._subscription_env())
    except (OSError, ValueError, RuntimeError):
        raise _refuse("binary_unavailable") from None
    except Exception:  # noqa: BLE001 - e.g. an unverified seat provider source
        raise _refuse("binary_unavailable") from None
    if identity[1] != expected:
        raise _refuse("binary_mismatch")
    return identity


def _help_and_version(binary: str, env: Mapping[str, str]) -> tuple[bytes, bytes]:
    """The literal bytes of ``--help`` and ``--version``, read exactly as the frozen branch
    of ``probe_grok_tools`` reads them (§4.1: ``text=False``, rc 0, empty stderr), so the
    digests a record binds are the ones the probe compares. 0 calls."""
    from . import panel_invoker as panel
    from . import sandbox_policy

    with tempfile.TemporaryDirectory(prefix="pl-tools-definition-") as directory:
        options = dict(cwd=directory, capture_output=True, text=False, timeout=30,
                       stdin=subprocess.DEVNULL, env=dict(env))

        def run(argv):
            return panel.run_provider(argv, child_scratch=sandbox_policy.CHILD_SCRATCH_RELOCATE,
                                      **options)

        try:
            help_result = run([binary, "--help"])
            version_result = run([binary, "--version"])
        except Exception:  # noqa: BLE001
            raise _refuse("help_unavailable") from None
    if (help_result.returncode != 0 or help_result.stderr != b""
            or type(help_result.stdout) is not bytes):
        raise _refuse("help_unavailable")
    if (b"--list-tools" in help_result.stdout
            and b"Print tool definitions without running a model" in help_result.stdout):
        # Basis selection is by the help gate alone (§4.1): a listing build is listed,
        # never measured.
        raise _refuse("listing_build")
    try:
        version = version_result.stdout.decode("utf-8")
    except (AttributeError, UnicodeDecodeError):
        raise _refuse("version_unavailable") from None
    if (version_result.returncode != 0 or version_result.stderr != b"" or not version.strip()
            or _VERSION_TEXT.fullmatch(version.rstrip("\n")) is None):
        raise _refuse("version_unavailable")
    return help_result.stdout, version_result.stdout


def launch_argv(form, *, cwd: str) -> list[str]:
    """The form with only its digest-masked slots filled (§5.4): the ``-p`` value is the
    fixed prompt and ``--cwd`` the empty scratch directory. No flag is added."""
    argv = list(form)
    for index, word in enumerate(argv[:-1]):
        if word == "-p":
            argv[index + 1] = MEASUREMENT_PROMPT
        elif word == "--cwd":
            argv[index + 1] = cwd
    return argv


def _prompt_on_stdin(form) -> bool:
    return any(word == "--prompt-file" and form[index + 1] == "/dev/stdin"
               for index, word in enumerate(form[:-1]))


def _admitted(form, tools: list[str]) -> bool:
    """``_grok_tools_admitted`` with the nonempty rule of §3.1, which ``record_tool_probe``
    applies to a receipt."""
    from . import panel_invoker as panel

    allowed = panel._grok_allowed_tools(form)
    return bool(panel._grok_tools_admitted(form, tools, allowed) and (bool(tools) or not allowed))


@dataclass
class _Stage:
    grant: Grant
    grant_dir: int
    output: int
    output_path: Path
    binary: str
    identity: tuple
    env: dict
    help_bytes: bytes
    version_bytes: bytes
    #: The reservation the route in progress holds, once it holds one.
    reserved: Reservation | None = None
    #: ``(reservation, revision)`` of each committed result whose local copy failed.
    local_copy_failed: set = field(default_factory=set)


def _base_result(stage: _Stage, reservation: Reservation, route: str, *, model: str,
                 context: str, allowlist_digest: str) -> dict[str, Any]:
    from .seat_window import _host_digest, runtime_digest

    return {
        "schema": RESULT_SCHEMA, "grant": stage.grant.id, "reservation": reservation.id,
        "route": route, "argv_digest": reservation.argv_digest,
        "binary_sha256": stage.identity[1],
        "version": stage.version_bytes.decode("utf-8").rstrip("\n"),
        "version_sha256": sha256(stage.version_bytes).hexdigest(),
        "help_sha256": sha256(stage.help_bytes).hexdigest(),
        "model": model, "effort": MEASUREMENT_EFFORT, "context": GROK_SEAT_CONTEXT,
        "context_digest": context, "host_digest": _host_digest(), "runtime_digest": runtime_digest(),
        "egress": {"allowlist_id": EGRESS_ALLOWLIST_ID, "allowlist_sha256": allowlist_digest},
        "prompt_sha256": sha256(MEASUREMENT_PROMPT.encode()).hexdigest(),
        "status": "interrupted", "eligible": route in ELIGIBLE_ROUTES, "admitted": None,
        "shape": None, "tools": None, "definitions_sha256": None, "definitions_bytes": None,
        "exit_code": None,
        "observation": {"complete": False, "reason": "not_started", "requests": 0, "counted": 0,
                        "denied": 0},
        "tolerated_refusals": [],
        "structure": None, "reprocessed_from": None, "revision": 0,
        "extractor": EXTRACTOR_REVISION, "at": _utc_now(),
    }


def _local_name(reservation_id: str, revision: int) -> str:
    return reservation_id + (f".r{revision}" if revision else "") + ".json"


def _write_result(stage: _Stage, result: dict[str, Any]) -> str:
    """Commit the immutable result record (§5.7): first with the grant, where it is the
    grant's one authoritative status whatever output directory a stage runs from, then its
    copy under ``<output>/results/``. Each is committed by :func:`_commit_new`, so a crash
    leaves it absent or complete and a retry commits the same revision cleanly. A revised
    record (§5.6) replaces its reservation's outcome only once the grant has it.

    Returns the local copy's state, ``present`` or ``failed``: once the grant has the record
    the result is committed, and a failure to write the copy is reported apart, never as a
    lost result (``--aggregate`` commits the copy again)."""
    check_result_keys(result)
    payload = _encode(result)
    committed = _subdir(stage.grant_dir, "results", create=False)
    try:
        _commit_new(committed, f"{result['reservation']}.{result['revision']}.json", payload)
    finally:
        os.close(committed)
    try:
        local = _subdir(stage.output, "results", create=True)
        try:
            _commit_new(local, _local_name(result["reservation"], result["revision"]), payload)
        finally:
            os.close(local)
    except (OSError, MeasurementRefused):
        stage.local_copy_failed.add((result["reservation"], result["revision"]))
        return "failed"
    return "present"


def _budget_denial(event: Any) -> bool:
    """The budget's own refusal of a request the allow-list itself admits: the proxy says
    the budget decided (``cause == "budget"``). The same method, host and path refused by
    any other check -- the inner Host check runs before the budget -- is not one."""
    from . import seat_egress_proxy

    return event.decision == "deny" and getattr(event, "cause", None) == "budget" and any(
        rule.get("host") == event.host and rule.get("method") == event.method
        and rule.get("path") == event.path
        for rule in seat_egress_proxy.allowlist_ref(EGRESS_ALLOWLIST_ID).request_set)


def _classify(*, early: str | None, exit_code: int | None, proof: Any, events, identity_ok: bool
              ) -> str | None:
    """The status a launch earns before its artifact is read (§5.5), or ``None`` when it
    may be read: exit 0, the identity unchanged, a complete observation with exactly one
    allowed counted request and no denial of any kind."""
    if early is not None:
        return early
    if not identity_ok:
        return "identity_changed"
    if proof is None or not proof.complete:
        return "egress_refused"
    # Erratum 3: a denial disqualifies unless it is one of the tolerated refusals, before or
    # after the counted request. Everything else still does: a second POST to the inference
    # host (budget_exhausted), a sign-in host, any other method, path or host.
    denied = [event for event in events if event.decision == "deny"
              and (event.method, event.host, event.path) not in TOLERATED_REFUSALS]
    if denied:
        if proof.counted >= PER_LAUNCH_BUDGET and any(_budget_denial(event) for event in denied):
            return "budget_exhausted"
        return "egress_refused"
    if any(event.decision == "allow" and not (event.method == "POST"
                                              and event.host == INFERENCE_HOST)
           for event in events):
        return "egress_refused"
    if proof.counted != 1:
        return "egress_refused"  # an unproxied attempt reaches nothing and may leave no event
    if exit_code != 0:
        return "launch_failed"
    return None


def _launch(stage: _Stage, *, proxy, prefix, argv, form, argv_digest, cwd: str, sessions: str,
            log_fd: int, request_budget: int = PER_LAUNCH_BUDGET,
            at_launch=None) -> tuple[str | None, int | None, tuple[bytes, ...]]:
    """One launch through ``seat_profile`` plus ``launch_owned(PROVIDER_REVIEW)`` (§5.1),
    inside the proxy-only namespace this launch owns. ``(early status, exit code, scan
    values)``: the last are the composed profile's ``scan_values`` (erratum 8, item 5), held
    in memory for the definitions scan and empty when nothing was composed."""
    from . import panel_invoker as panel

    token = panel._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
    try:
        admission = MeasurementAdmission(argv_digest=argv_digest, binary_sha256=stage.identity[1],
                                         egress_prefix=tuple(prefix), proxy=proxy, issuer=_ISSUER,
                                         request_budget=request_budget)
        with _holding(admission), contextlib.ExitStack() as stack:
            try:
                _require(panel.require_grok_admission([stage.binary, *argv[1:]], stage.env))
                provider, profile = stack.enter_context(panel.seat_profile(
                    harness="grok", executable=stage.binary, env=stage.env, cwd=cwd,
                    role=panel.SeatLaunchRole.PROVIDER_REVIEW, egress_proxy=proxy,
                    grok_sessions=sessions))
                _require(profile.dependency is None)
                verify_measurement_context(profile, cwd=cwd, command=argv, proxy=proxy,
                                           sessions=sessions)
            except Exception:  # noqa: BLE001 - no launch: the context does not hold
                return "context_refused", None, ()
            scan_values = profile.scan_values
            stdin_prompt = _prompt_on_stdin(form)
            # The launch boundary is the spawn itself: launch_provider calls ``at_launch``
            # (``spawn_hook``) after every check and argument of the launch is settled and
            # immediately before ``subprocess.Popen``, so a refusal anywhere before that --
            # the owner's admission, the live-holder check, the seat-identity probe, the
            # witness's arguments, a capped preflight -- launched nothing.
            try:
                process = panel.launch_owned(
                    [provider, *argv[1:]], role=panel.SeatLaunchRole.PROVIDER_REVIEW,
                    profile=profile, cwd=cwd, env=dict(profile.env),
                    stdin=subprocess.PIPE if stdin_prompt else subprocess.DEVNULL,
                    stdout=log_fd, stderr=log_fd, start_new_session=True,
                    **({"spawn_hook": at_launch} if at_launch is not None else {}))
            except Exception:  # noqa: BLE001
                return "launch_failed", None, scan_values
            try:
                if stdin_prompt and process.stdin is not None:
                    with contextlib.suppress(OSError):
                        process.stdin.write(MEASUREMENT_PROMPT.encode())
                    with contextlib.suppress(OSError):
                        process.stdin.close()
                try:
                    process.wait(timeout=LAUNCH_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    return "launch_failed", None, scan_values
            finally:
                panel._terminate_process_group(process)
            return None, process.returncode, scan_values
    finally:
        panel._EGRESS_LAUNCH_PREFIX.reset(token)


def _prepare_route(route: str) -> tuple[list[str], str, str, str]:
    """``(form, model, context digest, allow-list digest)`` for a launch of ``route``, after
    the refusals that come before any ledger entry: the route, the model, the egress layer,
    the namespace, the allow-list and managed configuration on the host."""
    from . import panel_invoker as panel
    from . import sandbox_egress, seat_egress_proxy

    if route not in MEASURED_ROUTES:
        raise _refuse("route_unavailable")
    form = panel.grok_runtime_forms(effort=MEASUREMENT_EFFORT)[route]
    model = form[form.index("-m") + 1]
    if model != MEASUREMENT_MODEL:
        raise _refuse("model_unavailable")
    if seat_egress_proxy.unavailable_reason() is not None:
        raise _refuse("egress_unavailable")
    if not sandbox_egress.egress_isolation_available():
        raise _refuse("egress_unavailable")
    try:
        context = context_digest()
        allowlist_digest = egress_allowlist_digest()
    except Exception:  # noqa: BLE001 - the allow-list is missing
        raise _refuse("egress_unavailable") from None
    try:
        _check_managed_config(())  # the host side now; the child's view after composition
    except _Refused:
        raise _refuse("context_refused") from None
    return form, model, context, allowlist_digest


def _measure_route(stage: _Stage, route: str) -> dict[str, Any]:
    """Exactly one launch of ``route``, never retried by the tool (§5.4). Refusals before
    the ledger raise :class:`MeasurementRefused` and leave nothing; once the route is
    reserved, every exit but a crash leaves a result record."""
    form, model, context, allowlist_digest = _prepare_route(route)
    from . import panel_invoker as panel

    argv_digest = panel._grok_argv_digest(form)
    scratch, scratch_lock = _new_scratch(stage.output_path)

    try:
        cwd = scratch / "cwd"
        sessions = scratch / "sessions"
        cwd.mkdir(mode=0o700)
        sessions.mkdir(mode=0o700)
        argv = launch_argv(form, cwd=str(cwd))
        if panel._grok_argv_digest(argv) != argv_digest:
            raise _refuse("argv_digest_mismatch")
        with _publication(stage.grant.binary_sha256) as root:
            ledger = _read_ledger(stage.grant_dir, stage.grant)
            reservation = _plan_reservation(ledger, route, argv_digest, context)
            # Crash-consistent withdrawal (§5.7, BA-2), each step durable before the next:
            # 1. this attempt becomes the latest and the route's publication is cleared, so
            #    a prior pass stops admitting from here on (host_route_current);
            # 2. the route leaves the host-local record;
            # 3. only then does the reservation exist.
            # A crash after 1 or 2 leaves the route unconsumable and nothing reserved.
            _record_attempt(root, stage.grant, reservation)
            _withdraw(root, stage.grant.binary_sha256, argv_digest)
            _write_reservation(stage.grant_dir, stage.grant, reservation)
            stage.reserved = reservation
        return _run_reserved(stage, reservation, route=route, form=form, argv=argv, model=model,
                             context=context, allowlist_digest=allowlist_digest, cwd=str(cwd),
                             sessions=str(sessions))
    finally:
        _drop_scratch(scratch, scratch_lock)


def _run_reserved(stage: _Stage, reservation: Reservation, *, route, form, argv, model, context,
                  allowlist_digest, cwd: str, sessions: str) -> dict[str, Any]:
    from . import panel_invoker as panel
    from . import seat_egress_proxy

    result = _base_result(stage, reservation, route, model=model, context=context,
                          allowlist_digest=allowlist_digest)
    raw = _subdir(stage.output, "raw", create=True)
    try:
        folder = _subdir(raw, reservation.id, create=True)
    finally:
        os.close(raw)
    try:
        _write_new(folder, "provider.log.expires_at",
                   f"{int(time.time()) + LOG_RETENTION_S}\n".encode())
        # Provider stdout and stderr are secret-bearing: kept private, never parsed (§5.9).
        log_fd = os.open("provider.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600, dir_fd=folder)
        proxy = None
        early: str | None = None
        exit_code: int | None = None
        scan_values: tuple[bytes, ...] = ()
        try:
            try:
                with panel._grok_review_egress(timeout_s=LAUNCH_TIMEOUT_S + 120.0,
                                               request_budget=PER_LAUNCH_BUDGET,
                                               named=TOLERATED_REFUSALS) as (proxy, prefix):
                    # scan_values: held by this frame for the definitions reader (erratum 8,
                    # item 5); dropped when the route returns.
                    early, exit_code, scan_values = _launch(
                                               stage, proxy=proxy, prefix=prefix, argv=argv,
                                               form=form, argv_digest=reservation.argv_digest,
                                               cwd=cwd, sessions=sessions, log_fd=log_fd)
            except Exception:  # noqa: BLE001 - the egress layer failed: nothing settles
                early = early or "egress_refused"
        finally:
            os.close(log_fd)
        _settle(stage.grant_dir, stage.grant, reservation, proxy)
        proof = events = None
        if proxy is not None and proxy.request_budget == PER_LAUNCH_BUDGET:
            proof = seat_egress_proxy.completion(proxy)
            events = seat_egress_proxy.proxy_stream(proxy).outside_events
            result["observation"] = {
                "complete": proof.complete, "reason": proof.reason, "requests": proof.requests,
                "counted": proof.counted,
                "denied": sum(1 for event in events if event.decision == "deny")}
            result["tolerated_refusals"] = tolerated_summary(events)
        try:
            identity_ok = panel._grok_probe_identity([stage.binary], stage.env) == stage.identity
        except Exception:  # noqa: BLE001
            identity_ok = False
        result["exit_code"] = exit_code
        status = _classify(early=early, exit_code=exit_code, proof=proof, events=events or (),
                           identity_ok=identity_ok)
        if status is None:
            status = _read_and_extract(result, form, folder, sessions)
        result["status"] = status
        if status == "measured":
            # Deleted at once on a measured route (§5.9).
            with contextlib.suppress(FileNotFoundError):
                os.unlink("provider.log", dir_fd=folder)
            with contextlib.suppress(FileNotFoundError):
                os.unlink("provider.log.expires_at", dir_fd=folder)
        result["at"] = _utc_now()
        _write_result(stage, result)
    finally:
        os.close(folder)
    return result


def _read_and_extract(result: dict[str, Any], form, folder: int, sessions: str) -> str:
    """Read the artifact (§5.5), retain a private copy (§5.9), extract (§5.6)."""
    try:
        directory = os.open(sessions, _dir_flags())
    except OSError:
        return "artifact_missing"
    try:
        raw = read_definitions(directory)
    except ArtifactRefused as refusal:
        return refusal.status
    finally:
        os.close(directory)
    _retain(folder, DEFINITIONS_NAME, raw, RAW_RETENTION_S)
    result["definitions_sha256"] = sha256(raw).hexdigest()
    result["definitions_bytes"] = len(raw)
    return _apply_extraction(result, form, raw)


def _apply_extraction(result: dict[str, Any], form, raw: bytes) -> str:
    try:
        shape, tools = extract_tool_names(raw)
    except FormatUnrecognised as refusal:
        result.update(shape=None, tools=None, admitted=None, structure=refusal.structure)
        return "format_unrecognised"
    result.update(shape=shape, tools=tools, admitted=_admitted(form, tools), structure=None)
    return "measured"


# ------------------------------------------------------------- rehearsal (erratum 4)

def _rehearsal_reason(*, early: str | None, proof: Any, events, identity_ok: bool) -> str:
    """Why a rehearsal passed or not. It passes only on a complete observation in which
    nothing was allowed, the launch reached its model request (the budget-0 proxy refused
    it as an allow-listed counted request), and every other refusal is a tolerated one of
    erratum 3. Anything else is a request the pilot would meet too, so the procedure stops
    before spending one."""
    if early is not None:
        return early
    if not identity_ok:
        return "identity_changed"
    if proof is None or not proof.complete:
        return "observation_incomplete"
    if any(event.decision == "allow" for event in events):
        return "unlisted_request"
    if any(not _budget_denial(event)
           and (event.method, event.host, event.path) not in TOLERATED_REFUSALS
           for event in events):
        return "unlisted_request"
    if not any(_budget_denial(event) for event in events):
        return "no_model_request"
    return "passed"


def rehearse(stage: _Stage, route: str) -> dict[str, Any]:
    """``--rehearse`` (erratum 4): the pilot's exact launch -- the same argv, composition,
    egress and admission -- under a proxy with ``request_budget=0``, so every request is
    refused and observed, nothing is forwarded and no model call is made. A credentialed
    launch within the grant that reserves, settles and charges nothing and is no planned
    launch or retry. One per grant. Its record is committed with the grant, metadata only;
    no reservation is made without a passing one. A session artifact it leaves is never a
    capture: it goes with the scratch directory and nothing is copied out."""
    from . import panel_invoker as panel
    from . import seat_egress_proxy

    form, _model, context, allowlist_digest = _prepare_route(route)
    if route not in stage.grant.planned:
        raise _refuse("route_not_planned")
    if route != stage.grant.planned[0]:
        raise _refuse("route_not_pilot")  # the rehearsal is the pilot's exact launch
    argv_digest = panel._grok_argv_digest(form)
    folder_fd = _subdir(stage.grant_dir, "rehearsals", create=True)
    try:
        _remove_commit_temps(folder_fd)
        if any(_REHEARSAL_NAME.fullmatch(name) or _ATTEMPT_NAME.fullmatch(name)
               for name in os.listdir(folder_fd)):
            # One rehearsal per grant, counted from the launch boundary: a rehearsal that
            # launched and left no record (a crash) is spent too. A second, after an
            # erratum, is a new grant.
            raise _refuse("rehearsal_exists")
        sequence = 1
    finally:
        os.close(folder_fd)
    rehearsal_id = f"{sequence:04d}-{secrets.token_hex(8)}"
    launched = []

    def mark_attempt() -> None:
        """The launch boundary, called by ``launch_provider`` at the spawn itself, after
        every check and argument of the launch path and immediately before
        ``subprocess.Popen`` creates the credentialed process: durably,
        before the child can start, this grant's one rehearsal is spent. A refusal before
        here leaves no marker and may be retried."""
        if launched:
            return
        folder = _subdir(stage.grant_dir, "rehearsals", create=True)
        try:
            _commit_new(folder, rehearsal_id + ".attempt.json", _encode({
                "schema": REHEARSAL_ATTEMPT_SCHEMA, "grant": stage.grant.id,
                "rehearsal": rehearsal_id, "route": route, "argv_digest": argv_digest,
                "binary_sha256": stage.identity[1], "context_digest": context,
                "at": _utc_now()}))
        finally:
            os.close(folder)
        launched.append(True)

    scratch, scratch_lock = _new_scratch(stage.output_path)
    proxy = None
    early: str | None = None
    exit_code: int | None = None
    log_folder = None
    try:
        cwd, sessions = scratch / "cwd", scratch / "sessions"
        cwd.mkdir(mode=0o700)
        sessions.mkdir(mode=0o700)
        argv = launch_argv(form, cwd=str(cwd))
        if panel._grok_argv_digest(argv) != argv_digest:
            raise _refuse("argv_digest_mismatch")
        raw = _subdir(stage.output, "raw", create=True)
        try:
            log_folder = _subdir(raw, "rehearsal-" + rehearsal_id, create=True)
        finally:
            os.close(raw)
        _write_new(log_folder, "provider.log.expires_at",
                   f"{int(time.time()) + LOG_RETENTION_S}\n".encode())
        log_fd = os.open("provider.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600, dir_fd=log_folder)
        try:
            try:
                with panel._grok_review_egress(timeout_s=LAUNCH_TIMEOUT_S + 120.0,
                                               request_budget=0,
                                               named=TOLERATED_REFUSALS) as (proxy, prefix):
                    early, exit_code, _scan_values = _launch(
                                               stage, proxy=proxy, prefix=prefix, argv=argv,
                                               form=form, argv_digest=argv_digest, cwd=str(cwd),
                                               sessions=str(sessions), log_fd=log_fd,
                                               request_budget=0, at_launch=mark_attempt)
            except Exception:  # noqa: BLE001 - the egress layer failed
                early = early or "egress_refused"
        finally:
            os.close(log_fd)
    except BaseException:
        if log_folder is not None:
            os.close(log_folder)
        raise
    finally:
        _drop_scratch(scratch, scratch_lock)
    if not launched:
        # Positively before the launch boundary -- the egress layer, the context, the
        # admission or a check inside the launch path refused, and no marker was written --
        # so this was no rehearsal: nothing is recorded and the grant keeps its one rehearsal.
        os.close(log_folder)
        raise _refuse("launch_refused" if early == "launch_failed" else early or "egress_refused")
    proof = events = None
    observation = {"complete": False, "reason": "not_started", "requests": 0, "counted": 0,
                   "denied": 0}
    if proxy is not None and proxy.request_budget == 0:
        proof = seat_egress_proxy.completion(proxy)
        events = seat_egress_proxy.proxy_stream(proxy).outside_events
        observation = {"complete": proof.complete, "reason": proof.reason,
                       "requests": proof.requests, "counted": proof.counted,
                       "denied": sum(1 for event in events if event.decision == "deny")}
    try:
        identity_ok = panel._grok_probe_identity([stage.binary], stage.env) == stage.identity
    except Exception:  # noqa: BLE001
        identity_ok = False
    reason = _rehearsal_reason(early=early, proof=proof, events=events or (),
                               identity_ok=identity_ok)
    incomplete = None
    if reason == "observation_incomplete":
        # What was missing, metadata only: the first unmet condition of the completion proof
        # and what the proxy's stream and shutdown showed (unknown without a budgeted proxy).
        incomplete = dict.fromkeys(_INCOMPLETE_KEYS)
        incomplete["missing"] = observation["reason"]
        if proxy is not None and proxy.request_budget == 0:
            incomplete.update(seat_egress_proxy.completion_detail(proxy))
    record = {
        "schema": REHEARSAL_SCHEMA, "grant": stage.grant.id, "rehearsal": rehearsal_id,
        "route": route, "argv_digest": argv_digest, "binary_sha256": stage.identity[1],
        "context_digest": context,
        "egress": {"allowlist_id": EGRESS_ALLOWLIST_ID, "allowlist_sha256": allowlist_digest},
        "status": "passed" if reason == "passed" else "failed", "reason": reason,
        "exit_code": exit_code, "observation": observation, "incomplete": incomplete,
        "budget_denials": sum(1 for event in events or () if _budget_denial(event)),
        "tolerated_refusals": tolerated_summary(events or ()),
        # Recorded for an erratum: the proxy's metadata-only observation.
        "observed": [{"method": event.method, "host": event.host, "path": event.path,
                      "decision": event.decision} for event in (events or ())][:_OBSERVED_CAP],
        "at": _utc_now()}
    check_rehearsal_keys(record)
    try:
        if reason == "passed":
            with contextlib.suppress(FileNotFoundError):
                os.unlink("provider.log", dir_fd=log_folder)
            with contextlib.suppress(FileNotFoundError):
                os.unlink("provider.log.expires_at", dir_fd=log_folder)
    finally:
        os.close(log_folder)
    folder_fd = _subdir(stage.grant_dir, "rehearsals", create=True)
    try:
        _commit_new(folder_fd, rehearsal_id + ".json", _encode(record))
    finally:
        os.close(folder_fd)
    return record


# --------------------------------------------------------------- reading results back

def _local_payloads(stage: _Stage, ledger: Ledger, *, strict: bool) -> dict[tuple[str, int], str]:
    """Per committed ``(reservation, revision)``, the state of its copy in this output
    directory: ``present`` or ``mismatch``; one not listed is ``missing``. With ``strict``
    (aggregation, §5.7) a result here that matches no committed record of this grant
    refuses."""
    states: dict[tuple[str, int], str] = {}
    local = _subdir(stage.output, "results", create=True)
    try:
        for name in sorted(os.listdir(local)):
            if name.startswith("."):
                continue
            match = _RESULT_NAME.fullmatch(name)
            key = None if match is None else (match.group(1), int(match.group(2) or 0))
            try:
                _require(key is not None and key in ledger.payloads)
                assert key is not None
                raw = _read_file(local, name, _RECORD_MAX_BYTES)
                _require(sha256(raw).hexdigest() == ledger.payloads[key])
                states[key] = "present"
            except (OSError, ValueError, TypeError):
                if strict:
                    raise _refuse("result_foreign") from None
                if key is not None and key in ledger.payloads:
                    states[key] = "mismatch"
    finally:
        os.close(local)
    return states


def _route_state(ledger: Ledger, local: Mapping[tuple[str, int], str], route: str
                 ) -> dict[str, Any]:
    """A route as ``--status`` and ``--require-measured`` report it, from the grant's
    committed records alone: ``no_reservation`` (nothing was ever reserved),
    ``interrupted`` (reserved, and no result ever committed), or ``recorded`` with the
    status of its latest reservation. ``local_payload`` says apart whether this output
    directory holds that record's copy (``present``, ``missing`` or ``mismatch``)."""
    latest = ledger.latest(route)
    if latest is None:
        return {"route": route, "state": "no_reservation"}
    result = ledger.latest_result(latest)
    if result is None:
        return {"route": route, "state": "interrupted", "reservation": latest.id}
    return {"route": route, "state": "recorded", "status": result["status"],
            "reservation": latest.id,
            "local_payload": local.get((latest.id, result["revision"]), "missing")}


# ------------------------------------------------------------- aggregation (§5.7, §5.8)

_SHARED = ("binary_sha256", "version", "version_sha256", "help_sha256", "model", "effort",
           "context_digest", "host_digest", "runtime_digest")


def aggregate(stage: _Stage, *, host_class: str) -> dict[str, Any]:
    """``--aggregate`` (no launch): the grant's evidence (§5.8) by temp file and rename,
    then the host-local record, which only this writes. Per route the latest reservation
    decides, and a route is published only when it is ``measured`` and eligible and the
    attempts register names this grant's own reservation as the latest by any grant;
    otherwise it is left out and reported ``superseded`` (BA-2). If aggregation fails or
    leaves no such route, any record for the binary is removed.

    The results are the grant's committed records, so any output directory aggregates the
    same grant the same way; a copy here that matches no committed record refuses, and a
    missing copy is committed again."""
    from .president_adapter import private_record_root, write_private_record
    from .seat_window import _host_digest

    binary = stage.grant.binary_sha256
    try:
        ledger = _read_ledger(stage.grant_dir, stage.grant)
        if ledger.unreadable or ledger.unreadable_results:
            raise _refuse("ledger_unreadable")
        local_states = _local_payloads(stage, ledger, strict=True)
        results = {item.id: result for item in ledger.reservations
                   if (result := ledger.latest_result(item)) is not None}
        if not results:
            raise _refuse("nothing_to_aggregate")
        documents = list(results.values())
        first = documents[0]
        if any(document[key] != first[key] for document in documents for key in _SHARED) or any(
                document["egress"] != first["egress"] for document in documents):
            raise _refuse("context_mismatch")
        if first["binary_sha256"] != binary or first["host_digest"] != _host_digest():
            raise _refuse("context_mismatch")
    except MeasurementRefused:
        with _publication(binary) as root:
            _remove_host_record(root, binary)
        raise
    routes = []
    for route in stage.grant.planned:
        latest = ledger.latest(route)
        if latest is None:
            continue
        result = results.get(latest.id)
        status = "interrupted" if result is None else result["status"]
        routes.append({
            "route": route, "argv_digest": latest.argv_digest, "status": status,
            "eligible": route in ELIGIBLE_ROUTES,
            "shape": None if result is None else result["shape"],
            "tools": None if result is None else result["tools"],
            "definitions_sha256": None if result is None else result["definitions_sha256"],
            "definitions_bytes": None if result is None else result["definitions_bytes"],
            "reservation": latest.id,
            "exit_code": None if result is None else result["exit_code"],
            "admitted": None if result is None else result["admitted"],
            "tolerated_refusals": [] if result is None else list(result["tolerated_refusals"]),
            "superseded": False})
    evidence = {
        "schema": EVIDENCE_SCHEMA, "binary_sha256": binary, "version": first["version"],
        "version_sha256": first["version_sha256"], "help_sha256": first["help_sha256"],
        "host_class": host_class, "host_digest": first["host_digest"],
        "runtime_digest": first["runtime_digest"], "context": GROK_SEAT_CONTEXT,
        "context_digest": first["context_digest"], "account_scope": "unbound",
        "method": "session_artifact", "model": first["model"], "effort": first["effort"],
        "egress": dict(first["egress"]), "prompt_sha256": first["prompt_sha256"],
        "grant": {"id": stage.grant.id, "planned": len(stage.grant.planned),
                  "retries": stage.grant.retries, "cap": stage.grant.cap,
                  "charged": ledger.charged(),
                  "other_grants_for_binary": other_grants_for_binary(stage.grant)},
        "reservations": [
            {"id": item.id, "at": item.at, "route": item.route, "budget": item.budget,
             "settled": ledger.settlements.get(item.id),
             "reprocessed": any(result["revision"] > 0
                                for result in ledger.results.get(item.id, ()))}
            for item in ledger.reservations],
        "routes": routes,
    }
    # A copy this output directory lacks is committed again from the grant's record.
    local = _subdir(stage.output, "results", create=True)
    try:
        for item in ledger.reservations:
            for result in ledger.results.get(item.id, ()):
                if (item.id, result["revision"]) not in local_states:
                    _commit_new(local, _local_name(item.id, result["revision"]), _encode(result))
    finally:
        os.close(local)
    with _publication(binary) as root:
        register = _read_register(root, binary)
        published = []
        for entry in routes:
            if entry["status"] != "measured" or not entry["eligible"]:
                continue
            latest_attempt = None if register is None else register.attempts.get(
                entry["argv_digest"])
            if latest_attempt is None or latest_attempt.get("grant") != stage.grant.id \
                    or latest_attempt.get("reservation") != entry["reservation"]:
                entry["superseded"] = True
                continue
            published.append(entry)
        check_evidence_keys(evidence)
        _replace_file(stage.output, "tool-surface.json", evidence)
        # The record goes first, then the register says what is published, then the record
        # is written: a crash between any two leaves nothing consumable (host_route_current).
        _remove_host_record(root, binary)
        surface = None
        if published:
            measured_at = max(results[entry["reservation"]]["at"] for entry in published)
            surface = {
                "binary_sha256": binary, "version": first["version"],
                "version_sha256": first["version_sha256"], "help_sha256": first["help_sha256"],
                "model": first["model"], "effort": first["effort"], "context": GROK_SEAT_CONTEXT,
                "context_digest": first["context_digest"], "measured_at": measured_at,
                "routes": [{"route": entry["route"], "argv_digest": entry["argv_digest"],
                            "tools": entry["tools"],
                            "definitions_sha256": entry["definitions_sha256"]}
                           for entry in published]}
            _check_surface(surface)
        if register is not None:
            publications = {}
            for route in (surface["routes"] if surface is not None else ()):
                entry = next(item for item in published if item["argv_digest"] == route["argv_digest"])
                publications[route["argv_digest"]] = {
                    "grant": stage.grant.id, "reservation": entry["reservation"],
                    "surface_digest": surface_digest(surface, route)}
            _write_register(root, binary, Register(attempts=register.attempts,
                                                   published=publications))
        if surface is not None and register is not None:
            write_private_record(host_record_name(binary), {
                "schema": HOST_RECORD_SCHEMA, "host_digest": _host_digest(), "surface": surface},
                root=private_record_root())
    return {"evidence": evidence, "published": [entry["route"] for entry in published],
            "superseded": [entry["route"] for entry in routes if entry["superseded"]]}


def reprocess(stage: _Stage, reservation_id: str) -> dict[str, Any]:
    """``--reprocess <reservation id>`` (§5.6): re-read the retained capture of a route left
    ``format_unrecognised`` with the current extractor and write a further result record for
    the same reservation. It reserves and charges nothing; the original charge stands."""
    from . import panel_invoker as panel

    ledger = _read_ledger(stage.grant_dir, stage.grant)
    reservation = next((item for item in ledger.reservations if item.id == reservation_id), None)
    if reservation is None:
        raise _refuse("reservation_unavailable")
    # The latest COMMITTED record decides: a revision whose commit was interrupted never
    # counted, so a retry writes that same revision again.
    previous = ledger.latest_result(reservation)
    if previous is None or previous["status"] != "format_unrecognised":
        raise _refuse("nothing_to_reprocess")
    raw_dir = _subdir(stage.output, "raw", create=True)
    try:
        try:
            folder = _subdir(raw_dir, reservation.id, create=False)
        except MeasurementRefused:
            raise _refuse("capture_unavailable") from None
    finally:
        os.close(raw_dir)
    try:
        try:
            deadline = int(_read_file(folder, DEFINITIONS_NAME + ".expires_at", 64))
            raw = _read_file(folder, DEFINITIONS_NAME, DEFINITIONS_MAX_BYTES)
        except (OSError, ValueError, TypeError):
            raise _refuse("capture_unavailable") from None
    finally:
        os.close(folder)
    if deadline <= time.time() or sha256(raw).hexdigest() != previous["definitions_sha256"]:
        raise _refuse("capture_unavailable")
    form = panel.grok_runtime_forms(effort=MEASUREMENT_EFFORT)[reservation.route]
    result = dict(previous)
    result.update(revision=previous["revision"] + 1, reprocessed_from=reservation.id,
                  extractor=EXTRACTOR_REVISION, at=_utc_now())
    result["status"] = _apply_extraction(result, form, raw)
    _write_result(stage, result)
    return result


# ---------------------------------------------------- the isolation self-check (BA-3)

_ISOLATION_CHILD = r"""#!/usr/bin/python3 -I
import base64, json, os, socket, sys, urllib.parse
canary, direct_ip, direct_port = sys.argv[1:4]
result = {}
parts = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
try:
    raw = socket.create_connection((parts.hostname, parts.port), 10)
    auth = base64.b64encode(f"{parts.username}:{parts.password}".encode()).decode()
    raw.sendall(f"CONNECT {canary}:443 HTTP/1.1\r\nHost: {canary}:443\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 65536:
        chunk = raw.recv(4096)
        if not chunk:
            break
        head += chunk
    raw.close()
    result["proxy"] = head.split(b"\r\n", 1)[0].decode("latin-1")[:64]
except OSError as exc:
    result["proxy"] = "error:" + type(exc).__name__
try:
    socket.create_connection((direct_ip, int(direct_port)), 3).close()
    result["direct"] = "connected"
except OSError as exc:
    result["direct"] = "refused:" + type(exc).__name__
print(json.dumps(result))
"""


def isolation_check(*, work_root: Path, timeout_s: float = 120.0) -> dict[str, Any]:
    """BA-3 on the measuring host, before any credential is projected: one child of the real
    launch-owner composition -- ``seat_profile(harness="grok", egress_proxy=...)`` plus
    ``launch_owned(PROVIDER_REVIEW)`` in the ``grok-review`` proxy-only namespace, with a
    fabricated, non-secret credential home and a stand-in child -- reaches THIS proxy (a
    random ``.invalid`` canary it asks for appears in this proxy's own observation stream)
    and fails a direct connection to a listener this host can reach at that moment. The
    proxy runs with budget 0, so nothing can be forwarded and no vendor is contacted. That a
    request through the proxy reaches an upstream is proven offline in CI against a fixture
    upstream. Returns ``{"passed": bool, "code": slug}``."""
    from . import panel_invoker as panel
    from . import sandbox_egress, seat_egress_proxy

    address = next((value for value in sandbox_egress.host_addresses()
                    if ":" not in value and not value.startswith("127.")), None)
    if address is None:
        return {"passed": False, "code": "isolation_host_unaddressable"}
    listener = socket.create_server((address, 0))
    try:
        listener.settimeout(5)
        port = listener.getsockname()[1]
        try:
            socket.create_connection((address, port), 3).close()
            listener.accept()[0].close()
        except OSError:
            return {"passed": False, "code": "isolation_listener_unreachable"}
        canary = secrets.token_hex(16) + ".invalid"
        work = Path(tempfile.mkdtemp(prefix="isolation-", dir=work_root))
        try:
            home = work / "home"
            (home / ".grok").mkdir(parents=True, mode=0o700)
            for relative, body in ((".grok/auth.json", b'{"key": "phase-loop-isolation-check"}'),
                                   (".grok/agent_id", b"phase-loop-isolation-check")):
                descriptor = os.open(home / relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(body)
            child = work / "isolation-child"
            descriptor = os.open(child, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(_ISOLATION_CHILD)
            cwd = work / "cwd"
            cwd.mkdir(mode=0o700)
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
            with panel._grok_review_egress(timeout_s=timeout_s + 60.0, request_budget=0) as (
                    proxy, prefix):
                if not bridged_to(prefix, proxy):
                    return {"passed": False, "code": "isolation_unproven"}
                token = panel._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
                try:
                    with panel.seat_profile(harness="grok", executable=str(child), env=env,
                                            cwd=cwd, egress_proxy=proxy) as (provider, profile):
                        process = panel.launch_owned(
                            [provider, canary, address, str(port)],
                            role=panel.SeatLaunchRole.PROVIDER_REVIEW, profile=profile,
                            cwd=str(cwd), env=dict(profile.env), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, start_new_session=True)
                        try:
                            out, _err = process.communicate(timeout=timeout_s)
                        finally:
                            panel._terminate_process_group(process)
                finally:
                    panel._EGRESS_LAUNCH_PREFIX.reset(token)
            events = seat_egress_proxy.proxy_stream(proxy).outside_events
        finally:
            shutil.rmtree(work, ignore_errors=True)
        listener.setblocking(False)
        try:
            listener.accept()[0].close()
            reached = True
        except (BlockingIOError, OSError):
            reached = False
    except Exception:  # noqa: BLE001 - a host where it cannot run is not eligible
        return {"passed": False, "code": "isolation_unproven"}
    finally:
        listener.close()
    try:
        report = json.loads(out.decode().strip().splitlines()[-1])
    except (ValueError, IndexError, UnicodeDecodeError):
        return {"passed": False, "code": "isolation_unproven"}
    observed = any(event.host == canary and event.decision == "deny" for event in events)
    passed = (process.returncode == 0 and str(report.get("proxy", "")).startswith("HTTP/1.1 403")
              and observed and str(report.get("direct", "")).startswith("refused:") and not reached)
    return {"passed": passed, "code": "isolation_proven" if passed else "isolation_unproven"}


# ------------------------------------------------------------------- the CLI (§5.10)

def _probe_rows(model=None, effort="high") -> list[dict[str, Any]]:
    from .seat_window import probe_tool_rows

    return probe_tool_rows(model=model, effort=effort)


def verify_probe(kind: str, *, expected: str, output: int, output_path: Path,
                 grant: Grant | None = None) -> dict[str, Any]:
    """``--verify-probe initial|final``: the probe of ``seat-window probe-tools``, compared
    route by route with what is expected; ``passed`` only on a match. Both first require the
    binary the probe itself resolves for ``grok`` to have the approved digest; ``initial``
    also requires the BA-3 isolation self-check, before any credential is projected."""
    from . import panel_invoker as panel

    try:
        resolved = panel._grok_probe_identity(["grok"], panel._subscription_env())[1]
    except Exception:  # noqa: BLE001
        resolved = None
    if resolved != expected:
        return {"passed": False, "code": "probe_binary_mismatch"}
    expected_rows: dict[str, tuple[bool, str]] = {}
    staging = None
    if kind == "initial":
        # Erratum 8, item 4: managed policy, read-only and before anything is projected.
        staging = managed_policy_staging()
        if not staging["passed"]:
            return {"passed": False, "code": "managed_config_present", "managed_policy": staging}
        isolation = isolation_check(work_root=output_path)
        if not isolation["passed"]:
            return {"passed": False, "code": isolation["code"]}
        rows = _probe_rows()
        expected_rows = {row["route"]: (False, "none") for row in rows}
    else:
        # Bound to this grant: the evidence must be this grant's aggregate, for this host
        # and binary, and name only this grant's reservations.
        from .seat_window import _host_digest

        if grant is None:
            return {"passed": False, "code": "grant_unavailable"}
        try:
            evidence = _read_doc(output, "tool-surface.json")
            check_evidence_keys(evidence)
            _require(evidence["schema"] == EVIDENCE_SCHEMA and evidence["binary_sha256"] == expected)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return {"passed": False, "code": "aggregate_unavailable"}
        reservations = {item["id"] for item in evidence["reservations"]}
        if (evidence["grant"]["id"] != grant.id or evidence["host_digest"] != _host_digest()
                or evidence["binary_sha256"] != grant.binary_sha256
                or not all(entry["reservation"] in reservations for entry in evidence["routes"])):
            return {"passed": False, "code": "aggregate_of_another_grant"}
        rows = _probe_rows()
        measured = {entry["route"]: entry for entry in evidence["routes"]}
        for row in rows:
            entry = measured.get(row["route"])
            ok = (entry is not None and row["route"] in ELIGIBLE_ROUTES
                  and entry["status"] == "measured" and entry["eligible"] is True
                  and entry["admitted"] is True and entry["superseded"] is False)
            expected_rows[row["route"]] = (True, "frozen_measurement") if ok else (False, "none")
    mismatches = [row["route"] for row in rows
                  if (row["passed"], row["basis"]) != expected_rows.get(row["route"])]
    report = {"passed": not mismatches, "code": "probe_matches" if not mismatches else "probe_mismatch",
              "routes": rows, "mismatches": mismatches}
    if staging is not None:
        report["managed_policy"] = staging
    return report


def _check_grant_if_present(grant_id: str, binary_sha256: str) -> None:
    """A stage that needs no grant still refuses a binary that differs from an existing
    ``grant.json`` (§5.10)."""
    try:
        directory, _grant = _open_grant(grant_id, binary_sha256=binary_sha256)
    except MeasurementRefused as refusal:
        if refusal.code == "grant_unavailable":
            return
        raise
    os.close(directory)


def _stage_flags(args) -> list[str]:
    flags = [name for name in ("new_grant", "aggregate", "status", "purge") if getattr(args, name, False)]
    if getattr(args, "rehearse", False):
        flags.append("rehearse")  # it takes its one route from --route
    elif getattr(args, "route", None):
        flags.append("route")
    for name in ("require_measured", "require_rehearsed", "verify_probe", "reprocess"):
        if getattr(args, name, None):
            flags.append(name)
    return flags


def measure_tools_cli(args) -> tuple[int, dict[str, Any]]:
    """``seat-window measure-tools``: one stage per invocation, ``(exit code, report)``."""
    from . import panel_invoker as panel

    flags = _stage_flags(args)
    if len(flags) != 1:
        return 2, {"status": "refused", "code": "one_stage_required"}
    stage_name = flags[0]
    try:
        _check_grant_id(args.grant)
        identity = _measure_binary(args.binary, args.expect_binary_sha256)
        output, output_path = _open_output(args.output)
    except MeasurementRefused as refusal:
        return 1, {"status": "refused", "code": refusal.code}
    try:
        try:
            expired = sweep_expired(output)
        except (OSError, MeasurementRefused):
            if stage_name in ("route", "rehearse"):
                return 1, {"status": "refused", "code": "expiry_sweep_failed"}
            expired = None
        report: dict[str, Any] = {"expired_removed": expired}
        if stage_name == "verify_probe":
            if args.verify_probe not in ("initial", "final"):
                return 2, {"status": "refused", "code": "one_stage_required"}
            grant = None
            if args.verify_probe == "final":
                # The final stage needs this grant; the initial stage may run before it.
                grant_dir, grant = _open_grant(args.grant, binary_sha256=identity[1])
                os.close(grant_dir)
            else:
                _check_grant_if_present(args.grant, identity[1])
            outcome = verify_probe(args.verify_probe, expected=identity[1], output=output,
                                   output_path=output_path, grant=grant)
            report.update(outcome)
            return (0 if outcome["passed"] else 1), report
        if stage_name == "purge":
            _check_grant_if_present(args.grant, identity[1])
            scratch = purge_scratch(output)
            report.update(removed=purge(output), **scratch)
            # Fail closed: retained data a purge could not remove is never reported as done.
            left = scratch["scratch_active"] or scratch["scratch_unknown"]
            report["status"] = "purge_incomplete" if left else "purged"
            return (1 if left else 0), report
        if stage_name == "new_grant":
            planned = [item for item in (args.planned or "").split(",") if item]
            retries = args.retries if args.retries is not None else -1
            grant = new_grant(args.grant, binary_sha256=identity[1], planned=planned,
                              retries=retries, hosted_check=args.hosted_check)
            report.update(status="opened", grant=grant.document())
            return 0, report
        grant_dir, grant = _open_grant(args.grant, binary_sha256=identity[1])
        try:
            with _flock(grant_dir, "lock", busy="measurement_busy"):
                stage = _Stage(grant=grant, grant_dir=grant_dir, output=output,
                               output_path=output_path, binary=args.binary, identity=identity,
                               env=dict(panel._subscription_env()), help_bytes=b"",
                               version_bytes=b"")
                return _run_stage(stage, stage_name, args, report)
        finally:
            os.close(grant_dir)
    except MeasurementRefused as refusal:
        return 1, {"status": "refused", "code": refusal.code}
    finally:
        os.close(output)


def _run_stage(stage: _Stage, stage_name: str, args, report: dict[str, Any]
               ) -> tuple[int, dict[str, Any]]:
    # A commit a crash interrupted left only a temp file; this stage holds the grant lock.
    committed = _subdir(stage.grant_dir, "results", create=False)
    try:
        _remove_commit_temps(committed)
    finally:
        os.close(committed)
    ledger = _read_ledger(stage.grant_dir, stage.grant)
    if stage_name == "status":
        local = _local_payloads(stage, ledger, strict=False)
        report.update(
            status="ok", grant=stage.grant.document(), charged=ledger.charged(),
            launches=ledger.launches(), retries_used=ledger.retries_used(),
            unreadable_reservations=ledger.unreadable,
            unreadable_results=ledger.unreadable_results, format_stop=ledger.format_stop(),
            rehearsal=next(({"rehearsal": item["rehearsal"], "route": item["route"],
                             "status": item["status"], "reason": item["reason"]}
                            for item in ledger.rehearsals), next(
                ({"rehearsal": item, "status": "interrupted"}
                 for item in ledger.rehearsal_unresolved()), None)),
            routes=[_route_state(ledger, local, route) for route in stage.grant.planned],
            reservations=[{"id": item.id, "route": item.route, "at": item.at,
                           "settled": ledger.settlements.get(item.id),
                           "status": ledger.status(item)} for item in ledger.reservations])
        return 0, report
    if stage_name == "require_measured":
        # "no reservation" is reported apart from "not measured" (§5.10), and both from an
        # interrupted attempt; the grant's committed record decides, whatever the output.
        state = _route_state(ledger, _local_payloads(stage, ledger, strict=False),
                             args.require_measured)
        recorded = state["state"] == "recorded"
        measured = recorded and state["status"] == "measured"
        report.update(route=state["route"], reservation=state.get("reservation"),
                      result=state.get("status"), local_payload=state.get("local_payload"),
                      status=("measured" if measured else "not_measured") if recorded
                      else state["state"])
        return (0 if measured else 1), report
    if stage_name == "require_rehearsed":
        # Erratum 4, step 5: the grant's passing rehearsal of this route, for its binary and
        # the context the code now enforces, or a non-zero exit and no pilot.
        route = args.require_rehearsed
        current = context_digest()
        records = [item for item in ledger.rehearsals if item["route"] == route]
        rehearsed = ledger.rehearsed(current, route)
        report.update(route=route, status="rehearsed" if rehearsed else (
            "not_rehearsed" if records else
            "interrupted" if ledger.rehearsal_unresolved() else "no_rehearsal"),
            reason=records[-1]["reason"] if records else None,
            rehearsal=records[-1]["rehearsal"] if records else None)
        return (0 if rehearsed else 1), report
    if stage_name == "aggregate":
        outcome = aggregate(stage, host_class=args.host_class)
        report.update(status="aggregated", published=outcome["published"],
                      superseded=outcome["superseded"])
        return 0, report
    if stage_name == "reprocess":
        result = reprocess(stage, args.reprocess)
        report.update(status="reprocessed", reservation=result["reservation"],
                      route=result["route"], result=result["status"],
                      local_copy="failed" if (result["reservation"], result["revision"])
                      in stage.local_copy_failed else "present")
        return 0, report
    # A launch stage: the rehearsal, and steps 4 and 6 of the procedure.
    if not args.attended:
        return 1, {**report, "status": "refused", "code": "attendance_required"}
    from . import panel_invoker as panel

    if stage_name == "rehearse":
        if not args.route or len(args.route) != 1:
            return 2, {**report, "status": "refused", "code": "one_route_to_rehearse"}
        if panel._grok_probe_identity([stage.binary], stage.env) != stage.identity:
            raise _refuse("binary_mismatch")
        record = rehearse(stage, args.route[0])
        report.update(status="rehearsed", route=record["route"], rehearsal=record["rehearsal"],
                      result=record["status"], reason=record["reason"],
                      observation=record["observation"], incomplete=record["incomplete"],
                      budget_denials=record["budget_denials"],
                      tolerated_refusals=record["tolerated_refusals"])
        return (0 if record["status"] == "passed" else 1), report

    stage.help_bytes, stage.version_bytes = _help_and_version(stage.binary, stage.env)
    if panel._grok_probe_identity([stage.binary], stage.env) != stage.identity:
        raise _refuse("binary_mismatch")
    rows: list[dict[str, Any]] = []
    code = 0
    for index, route in enumerate(args.route):
        stage.reserved = None
        try:
            result = _measure_route(stage, route)
        except Exception as exc:  # noqa: BLE001 - reported, and nothing later is launched
            if stage.reserved is not None:
                # The grant decides what happened: a result committed with it is recorded,
                # whatever failed after; only a reservation with none is interrupted (§5.7).
                ledger = _read_ledger(stage.grant_dir, stage.grant)
                committed = ledger.latest_result(stage.reserved)
                if committed is not None:
                    local = _local_payloads(stage, ledger, strict=False).get(
                        (stage.reserved.id, committed["revision"]), "missing")
                    rows.append({"route": route, "reserved": True,
                                 "reservation": stage.reserved.id,
                                 "status": committed["status"],
                                 "local_copy": "present" if local == "present" else "failed",
                                 "error": "after_commit"})
                    rows.extend({"route": later, "reserved": False, "code": "not_attempted"}
                                for later in args.route[index + 1:])
                    code = 1 if args.route[index + 1:] else code
                    break
                rows.append({"route": route, "reserved": True,
                             "reservation": stage.reserved.id, "status": "interrupted"})
            else:
                rows.append({"route": route, "reserved": False,
                             "code": exc.code if isinstance(exc, MeasurementRefused)
                             else "measurement_failed"})
            rows.extend({"route": later, "reserved": False, "code": "not_attempted"}
                        for later in args.route[index + 1:])
            code = 1
            break
        rows.append({"route": route, "reserved": True, "reservation": result["reservation"],
                     "status": result["status"],
                     "local_copy": "failed" if (result["reservation"], result["revision"])
                     in stage.local_copy_failed else "present"})
        if result["status"] == "interrupted":
            code = 1
    report.update(status="recorded" if code == 0 else "refused", routes=rows)
    return code, report
