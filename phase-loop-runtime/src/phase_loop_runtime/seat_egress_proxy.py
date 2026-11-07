"""The egress layer of a jailed Gemini seat (agent-harness#1170; plan agent-harness#1244,
rulings S3 and S4).

The seat's network namespace has no uplink. Its only way out is one loopback port, bridged
to a proxy that runs on the host, outside the seat: the TLS-terminating proxy of srt
(`@anthropic-ai/sandbox-runtime`, pinned below). The proxy answers only the requests on the
pinned allowlist (`seat_egress/gemini-allowlist.json`, measured from agy's real traffic),
checks the Host the client names inside each tunnel, and holds no credential. HTTPS_PROXY in
the seat is routing, not the boundary: a client that ignores it has no route at all.

The interception CA is this host's own (``ca_paths``): its directory is 0700 and its key
0600, owned by the operator. Only the certificate enters the seat, as the seat's whole trust
bundle; the key is read by the proxy alone and is never mounted, and the CA is never added to
the host's trust store.

Nothing here is fetched at run time. ``install`` runs ``npm ci`` against the shipped lockfile
(npm checks every package's integrity), and every launch re-checks the installed version,
the recorded integrities and the digest of the installed files.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterator, Literal, Mapping

from .seat_route_contract import AllowlistRef

__all__ = [
    "EgressLayerUnavailable",
    "FENCE_ACK_TIMEOUT_S",
    "FENCE_QUIET_S",
    "FenceResult",
    "ProxyStream",
    "ProxyWindow",
    "RequestEvent",
    "SeatEgressProxy",
    "SRT_VERSION",
    "allowlist",
    "allowlist_ref",
    "egress_evidence",
    "install",
    "fence",
    "proxy_stream",
    "start_proxy",
    "unavailable_code",
    "unavailable_reason",
]

SRT_PACKAGE = "@anthropic-ai/sandbox-runtime"
SRT_VERSION = "0.0.79"
SRT_INTEGRITY = ("sha512-WjBmS9fbTpnQwQkM9SU+JjhM2CcXo9eWEELktY1100RMvTy/jPhP44yZ3NXhh+GHB350"
                 "OgPbM3+FubE5WVRtSA==")
#: sha256 over every installed file (``tree_sha256``) of a clean ``npm ci`` of the shipped
#: lockfile: what was verified at install is what runs.
SRT_TREE_SHA256 = "a5039f84e95ab8f7994ef2a4e64b9293306811ba1eb7b67a055b7c8d7ea2aeaf"
NODE_MIN_VERSION = (22, 12, 0)
#: The seat's loopback port; the bridge listens here inside the seat's namespace.
SEAT_PROXY_PORT = 3128
UNAVAILABLE_CODE = "gemini_seat_egress_unavailable"
NOT_INSTALLED_CODE = "seat_egress_not_installed"
INTEGRITY_CODE = "seat_egress_integrity_failed"
TLS_UNTERMINATED_CODE = "seat_egress_tls_unterminated"
START_FAILED_CODE = "seat_egress_start_failed"
ALLOWLIST_MISSING_CODE = "seat_egress_allowlist_missing"
INSTALL_FIX = "phase-loop seat-egress install"
_DATA = "seat_egress"
_READY_TIMEOUT_S = 60.0
_CA_CAP_BYTES = 64 * 1024
#: Contract section 14: the wrapper counts a fence only when its id is acknowledged within
#: this bound; the proxy acknowledges after this quiet interval with no open connection.
FENCE_ACK_TIMEOUT_S = 10.0
FENCE_QUIET_S = 2.0
#: Bound on the observation stream of one proxy instance; beyond it the stream is incomplete.
_STREAM_ITEM_CAP = 16384
#: The section 9 token-endpoint hosts. They are part of the event host vocabulary.
TOKEN_ENDPOINT_HOSTS = frozenset({"oauth2.googleapis.com", "accounts.google.com",
                                  "sts.googleapis.com", "iamcredentials.googleapis.com",
                                  "www.googleapis.com"})
_EVENT_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
                            "CONNECT", "<other>"})
_CANARY_HOST = re.compile(r"[0-9a-f]{32}\.invalid")
_FENCE_ID = re.compile(r"[0-9a-f]{32}")
_ALLOWLIST_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class EgressLayerUnavailable(RuntimeError):
    """The seat's egress layer cannot run on this host, with one typed cause."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        super().__init__(reason)


def _data_path(name: str) -> Path:
    return Path(str(resources.files("phase_loop_runtime").joinpath(_DATA, name)))


def allowlist(allowlist_id: str = "gemini") -> dict[str, object]:
    """Load and validate one pinned request allowlist."""
    if not isinstance(allowlist_id, str) or _ALLOWLIST_ID.fullmatch(allowlist_id) is None:
        raise EgressLayerUnavailable(ALLOWLIST_MISSING_CODE, "the seat egress allowlist id is invalid")
    path = _data_path(f"{allowlist_id}-allowlist.json")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EgressLayerUnavailable(
            ALLOWLIST_MISSING_CODE, f"the seat egress allowlist is not installed: {allowlist_id}",
        ) from exc
    except OSError as exc:
        raise EgressLayerUnavailable(
            INTEGRITY_CODE, f"the seat egress allowlist cannot be read: {allowlist_id}",
        ) from exc
    try:
        document = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise EgressLayerUnavailable(
            INTEGRITY_CODE, f"the seat egress allowlist is malformed: {allowlist_id}",
        ) from exc
    if not isinstance(document, dict):
        raise EgressLayerUnavailable(
            INTEGRITY_CODE, f"the seat egress allowlist is malformed: {allowlist_id}",
        )
    _validate_allowlist_document(allowlist_id, document)
    return document


def _validate_allowlist_document(allowlist_id: str, document: Mapping[str, object]) -> None:
    if document.get("schema") != "phase_loop_seat_egress_allowlist.v1":
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress allowlist schema is invalid")
    if document.get("leg") != allowlist_id:
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress allowlist leg is invalid")
    rules = document.get("allow")
    refused = document.get("measured_and_refused")
    if not isinstance(rules, list) or not isinstance(refused, list):
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress allowlist rows are invalid")
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) not in (
            {"host", "port", "method", "path"},
            {"host", "port", "method", "path_prefix"},
        ):
            raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress allowlist rule is invalid")
        if (not isinstance(rule["host"], str) or not rule["host"]
                or type(rule["port"]) is not int or rule["port"] != 443
                or not isinstance(rule["method"], str) or not rule["method"]):
            raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress allowlist rule is invalid")
        path_key = "path" if "path" in rule else "path_prefix"
        if not isinstance(rule[path_key], str) or not rule[path_key].startswith("/"):
            raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress allowlist rule is invalid")
    if any(not isinstance(host, str) or not host for host in refused):
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the seat egress refusal rows are invalid")


def _probe_rows(
    rules: list[object], refused: list[object],
) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = [
        {"decision": "allow", **dict(rule)} for rule in rules if isinstance(rule, dict)
    ]
    rows.extend({
        "decision": "refuse", "host": host, "port": 443, "method": "CONNECT",
    } for host in refused if isinstance(host, str))
    rows.append({
        "decision": "refuse", "host": "seat-egress-unlisted.invalid", "port": 443,
        "method": "CONNECT",
    })
    return tuple(rows)


def allowlist_ref(allowlist_id: str) -> AllowlistRef:
    """Load one packaged allowlist and bind every request and refusal row."""
    document = allowlist(allowlist_id)
    rules = document["allow"]
    refused = document["measured_and_refused"]
    assert isinstance(rules, list) and isinstance(refused, list)
    bound = {
        key: document[key] for key in ("schema", "leg", "allow", "measured_and_refused")
    }
    return AllowlistRef(
        id=allowlist_id,
        content_digest=_digest(bound),
        request_set=tuple(dict(rule) for rule in rules if isinstance(rule, dict)),
        probe_rows=_probe_rows(rules, refused),
    )


def _data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    return Path(configured) if configured and os.path.isabs(configured) else (
        Path.home() / ".local" / "share")


def install_root() -> Path:
    return _data_home() / "phase-loop" / "seat-egress" / f"srt-{SRT_VERSION}"


def ca_dir() -> Path:
    from .seat_jail import state_home

    return state_home() / "phase-loop" / "seat-egress-ca"


def ca_paths() -> tuple[Path, Path]:
    """``(certificate, key)`` of this host's seat egress CA."""
    return ca_dir() / "ca.crt", ca_dir() / "ca.key"


def tree_sha256(root: Path) -> str:
    """sha256 over ``(path, sha256(bytes))`` of every regular file under ``root``, in path
    order, leaving out npm's own record (``.package-lock.json``) and the ``.bin`` links."""
    digest = hashlib.sha256()
    entries = []
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == ".package-lock.json" or relative.startswith(".bin/") or path.is_symlink():
                continue
            entries.append((relative, path))
    for relative, path in sorted(entries):
        digest.update(relative.encode("utf-8") + b"\0"
                      + hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def reject_unexpected_symlinks(root: Path) -> None:
    """Raise if the installed tree holds a symlink anywhere but ``node_modules/.bin/``.

    The digest (``tree_sha256``) skips symlinks and ``os.walk`` does not descend symlinked
    directories, so a link that redirects Node's module resolution (e.g. a ``dist`` or
    ``node_modules`` link) would change what runs while the digest stayed the same
    (agent-harness#1170 F007). A clean ``npm ci`` tree has links only under ``.bin``; any
    other is refused, so the digest covers what actually runs."""
    for directory, dirs, files in os.walk(root):
        rel_dir = Path(directory).relative_to(root).as_posix()
        for name in (*dirs, *files):
            relative = name if rel_dir == "." else f"{rel_dir}/{name}"
            if relative == ".bin" or relative.startswith(".bin/"):
                continue
            if (Path(directory) / name).is_symlink():
                raise EgressLayerUnavailable(INTEGRITY_CODE,
                    f"the installed srt tree has an unexpected symlink: {relative}")


def _node() -> str:
    from .review_stage import trusted_host_executable

    try:
        node = trusted_host_executable("node")
    except ValueError as exc:
        raise EgressLayerUnavailable(NOT_INSTALLED_CODE, "node is not installed") from exc
    try:
        found = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30,
                               env=_proxy_env(node, None), check=False).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise EgressLayerUnavailable(NOT_INSTALLED_CODE, "node does not run") from exc
    match = re.match(r"v(\d+)\.(\d+)\.(\d+)", found.strip())
    if match is None or tuple(int(part) for part in match.groups()) < NODE_MIN_VERSION:
        raise EgressLayerUnavailable(NOT_INSTALLED_CODE,
            "node {}.{}.{} or newer is required".format(*NODE_MIN_VERSION))
    return node


def _proxy_env(node: str, home: Path | None) -> dict[str, str]:
    """The proxy's whole environment: nothing from the operator's, so no credential, proxy
    or trust setting reaches it."""
    env = {"PATH": f"{Path(node).parent}:/usr/bin:/bin", "LANG": "C.UTF-8"}
    if home is not None:
        env["HOME"] = str(home)
    return env


def verify_install(root: Path | None = None) -> Path:
    """The installed srt entry point, after checking it is the pinned package, byte for
    byte. Raises :class:`EgressLayerUnavailable`."""
    root = root or install_root()
    modules = root / "node_modules"
    installed_path = modules / SRT_PACKAGE / "package.json"
    recorded_path = modules / ".package-lock.json"
    if not os.path.lexists(installed_path) or not os.path.lexists(recorded_path):
        raise EgressLayerUnavailable(NOT_INSTALLED_CODE, "srt is not installed")
    try:
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
        recorded = json.loads(recorded_path.read_text(encoding="utf-8"))
        shipped = json.loads(_data_path("package-lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed srt record is invalid") from exc
    if installed.get("version") != SRT_VERSION:
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed srt is not the pinned version")
    packages = recorded.get("packages") if isinstance(recorded, dict) else None
    if not isinstance(packages, dict):
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed srt has no package record")
    for name, entry in shipped["packages"].items():
        if not name:
            continue
        if (packages.get(name, {}).get("integrity") != entry["integrity"]
                or packages.get(name, {}).get("version") != entry["version"]):
            raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed packages are not the pinned ones")
    if packages.get(f"node_modules/{SRT_PACKAGE}", {}).get("integrity") != SRT_INTEGRITY:
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed srt is not the pinned package")
    try:
        # Reject links first: the digest skips them, so the resolution boundary (what Node
        # actually loads) must be link-free outside .bin for the digest to cover what runs.
        reject_unexpected_symlinks(modules)
        if tree_sha256(modules) != SRT_TREE_SHA256:
            raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed srt files changed after install")
    except OSError as exc:
        raise EgressLayerUnavailable(INTEGRITY_CODE, "the installed srt cannot be read") from exc
    return modules / SRT_PACKAGE / "dist" / "index.js"


def install(root: Path | None = None) -> Path:
    """Install the pinned srt with ``npm ci`` (integrity-checked against the shipped
    lockfile; no install scripts run), then verify it."""
    from .review_stage import trusted_host_executable

    root = root or install_root()
    node = _node()
    try:
        npm = trusted_host_executable("npm")
    except ValueError as exc:
        raise EgressLayerUnavailable(NOT_INSTALLED_CODE, "npm is not installed") from exc
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(_data_path(name), root / name)
    with tempfile.TemporaryDirectory(prefix="pl-seat-egress-npm-") as home:
        done = subprocess.run(
            [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--omit=dev"],
            cwd=root, env=_proxy_env(node, Path(home)), capture_output=True, text=True,
            timeout=600, check=False)
    if done.returncode != 0:
        raise EgressLayerUnavailable(
            START_FAILED_CODE, f"npm ci failed: {done.stderr.strip()[-200:]}")
    return verify_install(root)


def _private_dir_problem(path: Path) -> str | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        return "not owned"
    if stat.S_IMODE(info.st_mode) & 0o077:
        return "not 0700"
    return None


def _private_file_problem(path: Path, *, key: bool) -> str | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        return "not owned"
    if stat.S_IMODE(info.st_mode) & (0o077 if key else 0o022):
        return "not 0600" if key else "writable by others"
    if info.st_size > _CA_CAP_BYTES:
        return "too large"
    return None


def ensure_ca(srt_index: Path, node: str) -> tuple[Path, Path]:
    """This host's CA, generated on first use with srt's own generator. Its directory must
    be the operator's alone (0700), its key 0600; anything else refuses."""
    directory = ca_dir()
    cert, key = ca_paths()
    problem = _private_dir_problem(directory)
    if problem == "missing":
        try:
            directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.mkdir(mode=0o700)
        except OSError as exc:
            raise EgressLayerUnavailable(
                START_FAILED_CODE, "the seat egress CA directory could not be created",
            ) from exc
        problem = None
    if problem is not None:
        raise EgressLayerUnavailable(
            INTEGRITY_CODE, f"the seat egress CA directory is {problem}: {directory}")
    if not os.path.lexists(cert) and not os.path.lexists(key):
        try:
            done = subprocess.run(
                [node, str(_data_path("ca.mjs")), str(srt_index), str(directory)],
                env=_proxy_env(node, directory), capture_output=True, text=True,
                timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise EgressLayerUnavailable(
                START_FAILED_CODE, "the seat egress CA could not be generated",
            ) from exc
        if done.returncode != 0:
            raise EgressLayerUnavailable(
                START_FAILED_CODE, "the seat egress CA could not be generated")
    for path, is_key in ((cert, False), (key, True)):
        problem = _private_file_problem(path, key=is_key)
        if problem is not None:
            raise EgressLayerUnavailable(
                INTEGRITY_CODE, f"the seat egress CA {path.name} is {problem}")
    return cert, key


def unavailable_reason() -> str | None:
    """``None`` when this host can run the seat's egress layer, else the one reason. Read
    only, except that it creates this host's CA on first use."""
    try:
        node = _node()
        ensure_ca(verify_install(), node)
    except EgressLayerUnavailable as exc:
        return str(exc)
    return None


def unavailable_code() -> str | None:
    """``None`` when the layer is ready, otherwise its stable route code."""
    try:
        node = _node()
        ensure_ca(verify_install(), node)
    except EgressLayerUnavailable as exc:
        return exc.code
    return None


@dataclass
class SeatEgressProxy:
    """One running proxy. ``proxy_url`` carries the proxy's per-launch session token (it
    admits a client to this proxy and grants nothing else); it is placeholdered wherever an
    argv is recorded."""

    socket: str
    proxy_url: str = field(repr=False)
    ca_cert: Path
    ca_sha256: str
    inner_sni_check: bool
    process: "subprocess.Popen[str]" = field(repr=False)
    allowlist_id: str = "gemini"
    allowlist_digest: str = ""
    #: FROZEN-NEW (I-1): sha256 of the canonical JSON of the ``allow`` list passed to the
    #: proxy; that of ``[]`` under ``refuse_all``.
    allowlist_sha256: str = ""
    _rules: tuple = field(default=(), repr=False)
    _items: list = field(default_factory=list, repr=False)
    _fences: list = field(default_factory=list, repr=False)
    _protocol_error: bool = field(default=False, repr=False)
    _eof: bool = field(default=False, repr=False)
    _exited: bool = field(default=False, repr=False)
    _outstanding: str | None = field(default=None, repr=False)
    _acked: dict = field(default_factory=dict, repr=False)
    _cond: threading.Condition = field(default_factory=threading.Condition, repr=False)
    _fence_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _reader: threading.Thread | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class FenceResult:
    """One fence (contract section 14). ``acked_ns`` is ``time.monotonic_ns()`` at the
    acknowledgement."""

    fence_id: str
    acknowledged: bool
    acked_ns: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestEvent:
    """One request decision, in the proxy's closed vocabulary. ``host`` and ``path`` are
    private-record fields."""

    method: str
    host: str
    path: str | None
    decision: Literal["allow", "deny"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProxyWindow:
    label: Literal["leg", "bracket"]
    start_acked: bool
    end_acked: bool
    events: tuple[RequestEvent, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProxyStream:
    """One instance's observation stream. ``final`` only once the proxy context has exited
    and stdout reached EOF; events outside every window stay in ``outside_events``."""

    final: bool
    protocol_error: bool
    windows: tuple[ProxyWindow, ...]
    outside_events: tuple[RequestEvent, ...]
    allowlist_sha256: str


def fence(proxy: SeatEgressProxy, marker: Literal["start", "end"],
          window: Literal["leg", "bracket"]) -> FenceResult:
    """Send one fence with a fresh id and wait up to :data:`FENCE_ACK_TIMEOUT_S` for its
    acknowledgement (contract section 14). Nothing is sent, and the result is
    unacknowledged, while a fence is outstanding or the stream has a protocol error. A
    timeout sets the protocol error."""
    if marker not in ("start", "end") or window not in ("leg", "bracket"):
        raise ValueError("unknown fence marker or window")
    fence_id = secrets.token_hex(16)
    if not proxy._fence_lock.acquire(blocking=False):
        return FenceResult(fence_id=fence_id, acknowledged=False, acked_ns=None)
    try:
        with proxy._cond:
            if proxy._outstanding is not None or proxy._protocol_error or proxy._eof:
                return FenceResult(fence_id=fence_id, acknowledged=False, acked_ns=None)
            proxy._outstanding = fence_id
            proxy._fences.append((marker, window, fence_id))
        try:
            assert proxy.process.stdin is not None
            proxy.process.stdin.write(json.dumps({"op": "fence", "id": fence_id},
                                                 separators=(",", ":")) + "\n")
            proxy.process.stdin.flush()
        except (OSError, ValueError, AssertionError):
            with proxy._cond:
                proxy._outstanding = None
                proxy._protocol_error = True
            return FenceResult(fence_id=fence_id, acknowledged=False, acked_ns=None)
        deadline = time.monotonic() + FENCE_ACK_TIMEOUT_S
        with proxy._cond:
            while fence_id not in proxy._acked and not proxy._eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                proxy._cond.wait(remaining)
            if fence_id in proxy._acked:
                return FenceResult(fence_id=fence_id, acknowledged=True,
                                   acked_ns=proxy._acked[fence_id])
            # A late acknowledgement is then unsolicited as well.
            proxy._outstanding = None
            proxy._protocol_error = True
            return FenceResult(fence_id=fence_id, acknowledged=False, acked_ns=None)
    finally:
        proxy._fence_lock.release()


def proxy_stream(proxy: SeatEgressProxy) -> ProxyStream:
    """The instance's stream split into its fenced windows. An event belongs to a window
    only between that window's start and end acknowledgements, in stdout order."""
    with proxy._cond:
        items = list(proxy._items)
        fences = list(proxy._fences)
        final = proxy._eof and proxy._exited
        protocol_error = proxy._protocol_error
    position = {item[1]: index for index, item in enumerate(items) if item[0] == "fence"}
    windows: list[ProxyWindow] = []
    covered: set[int] = set()
    pending: dict[str, str] = {}
    for marker, label, fence_id in fences:
        if marker == "start":
            pending[label] = fence_id
            continue
        start_id = pending.pop(label, None)
        lo = position.get(start_id) if start_id else None
        hi = position.get(fence_id)
        events: tuple[RequestEvent, ...] = ()
        if lo is not None and hi is not None and lo < hi:
            covered.update(range(lo + 1, hi))
            events = tuple(items[i][1] for i in range(lo + 1, hi) if items[i][0] == "request")
        windows.append(ProxyWindow(label=label, start_acked=lo is not None,
                                   end_acked=hi is not None, events=events))
    for label, start_id in pending.items():
        windows.append(ProxyWindow(label=label, start_acked=start_id in position,
                                   end_acked=False, events=()))
    outside = tuple(item[1] for index, item in enumerate(items)
                    if item[0] == "request" and index not in covered)
    return ProxyStream(final=final, protocol_error=protocol_error, windows=tuple(windows),
                       outside_events=outside, allowlist_sha256=proxy.allowlist_sha256)


def _read_stream(proxy: SeatEgressProxy) -> None:
    assert proxy.process.stdout is not None
    try:
        for line in proxy.process.stdout:
            _accept(proxy, line)
    except (OSError, ValueError):
        with proxy._cond:
            proxy._protocol_error = True
    finally:
        with proxy._cond:
            proxy._eof = True
            proxy._cond.notify_all()


def _accept(proxy: SeatEgressProxy, line: str) -> None:
    try:
        item = json.loads(line)
    except ValueError:
        item = None
    with proxy._cond:
        if len(proxy._items) >= _STREAM_ITEM_CAP:
            proxy._protocol_error = True
            return
        if _valid_request_event(item, proxy._rules):
            proxy._items.append(("request", RequestEvent(
                method=item["method"], host=item["host"], path=item["path"],
                decision=item["decision"])))
        elif (isinstance(item, dict) and set(item) == {"event", "id"}
              and item["event"] == "fence" and isinstance(item["id"], str)
              and item["id"] == proxy._outstanding):
            proxy._items.append(("fence", item["id"]))
            proxy._acked[item["id"]] = time.monotonic_ns()
            proxy._outstanding = None
            proxy._cond.notify_all()
        else:
            # An unknown line, or a mismatched or unsolicited acknowledgement.
            proxy._protocol_error = True


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _path_templates(rules, host: str) -> set:
    """The templated paths an event for ``host`` may carry (I-2's closed vocabulary)."""
    paths = {"/oauth2/v2/userinfo", "/oauth2/*", "<other>", None}
    paths.update(r["path"] if "path" in r else r.get("path_prefix", "") + "*"
                 for r in rules if r["host"] == host)
    return paths


def _valid_request_event(item, rules) -> bool:
    """The five-field request event, in the proxy's closed vocabulary, and nothing else."""
    if not isinstance(item, dict) or set(item) != {"event", "method", "host", "path", "decision"}:
        return False
    host = item["host"]
    if item["event"] != "request" or item["method"] not in _EVENT_METHODS:
        return False
    if item["decision"] not in ("allow", "deny"):
        return False
    if not isinstance(host, str) or not (
            host == "<other>" or host in TOKEN_ENDPOINT_HOSTS
            or any(r["host"] == host for r in rules) or _CANARY_HOST.fullmatch(host)):
        return False
    path = item["path"]
    if path is not None and not isinstance(path, str):
        return False
    return path in _path_templates(rules, host)


def ca_fingerprint(cert: Path) -> str:
    """sha256 of the CA certificate's DER bytes, the form trust stores are keyed by."""
    import ssl

    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))).hexdigest()


@contextlib.contextmanager
def start_proxy(*, allowlist_id: str,
                refuse_all: bool = False) -> Iterator[SeatEgressProxy]:
    """Run the seat's proxy for the life of the context. Raises
    :class:`EgressLayerUnavailable` before anything runs when the layer is unavailable.

    ``refuse_all`` (contract section 15, the credential-free controls) passes an empty
    rule list through the proxy's existing configuration file; it can only narrow the
    rules, and the production allowlist file is unchanged. The proxy's observation stream
    and fences go through :func:`fence` and :func:`proxy_stream`."""
    node = _node()
    srt_index = verify_install()
    cert, key = ensure_ca(srt_index, node)
    selected = allowlist_ref(allowlist_id)
    rules = [] if refuse_all is True else list(selected.request_set)
    try:
        workspace = tempfile.TemporaryDirectory(prefix="pl-seat-egress-")
    except OSError as exc:
        raise EgressLayerUnavailable(
            START_FAILED_CODE, "the seat egress proxy workspace could not be created") from exc
    with workspace as work:
        config = Path(work) / "proxy.json"
        try:
            config.write_text(json.dumps({
                "allow": rules, "ca_cert": str(cert), "ca_key": str(key),
                "inner_sni_check": True,
            }), encoding="utf-8")
            process = subprocess.Popen(
                [node, str(_data_path("proxy.mjs")), str(srt_index), str(config)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=_proxy_env(node, Path(work)), cwd=work, text=True, start_new_session=True)
        except (OSError, ValueError) as exc:
            raise EgressLayerUnavailable(
                START_FAILED_CODE, "the seat egress proxy could not be started") from exc
        proxy: SeatEgressProxy | None = None
        try:
            ready = _read_ready(process)
            if not all(ready.get(name) is True for name in (
                "tls_inspection", "inner_sni_check", "fail_closed_front",
            )):
                raise EgressLayerUnavailable(
                    TLS_UNTERMINATED_CODE,
                    "the proxy did not attest its fail-closed TLS front",
                )
            token = str(ready["token"])
            try:
                ca_sha256 = ca_fingerprint(cert)
            except (OSError, ValueError) as exc:
                raise EgressLayerUnavailable(
                    INTEGRITY_CODE, "the seat egress CA certificate is invalid") from exc
            proxy = SeatEgressProxy(
                socket=str(ready["socket"]),
                proxy_url=f"http://srt:{token}@127.0.0.1:{SEAT_PROXY_PORT}",
                ca_cert=cert, ca_sha256=ca_sha256,
                inner_sni_check=True, process=process,
                allowlist_id=selected.id, allowlist_digest=selected.content_digest,
                allowlist_sha256=_digest(rules), _rules=tuple(rules))
            proxy._reader = threading.Thread(target=_read_stream, args=(proxy,), daemon=True,
                                             name="seat-egress-stream")
            proxy._reader.start()
            yield proxy
        finally:
            with contextlib.suppress(OSError, ValueError):
                if process.stdin is not None:
                    process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if proxy is not None and proxy._reader is not None:
                proxy._reader.join(timeout=5)
                with proxy._cond:
                    proxy._exited = True
                    if proxy._reader.is_alive():
                        proxy._protocol_error = True
            if process.stdout is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stdout.close()


def _read_ready(process: "subprocess.Popen[str]") -> Mapping[str, object]:
    import select

    assert process.stdout is not None
    try:
        readable, _, _ = select.select([process.stdout], [], [], _READY_TIMEOUT_S)
        line = process.stdout.readline() if readable else ""
        ready = json.loads(line)
    except (OSError, ValueError):
        ready = None
    if (not isinstance(ready, dict) or not isinstance(ready.get("socket"), str)
            or not ready["socket"] or not isinstance(ready.get("token"), str)
            or not ready["token"]):
        raise EgressLayerUnavailable(
            START_FAILED_CODE, "the seat egress proxy did not start")
    return ready


def egress_evidence(proxy: SeatEgressProxy) -> dict[str, object]:
    """What the seat's egress layer enforced, for the leg's evidence."""
    rules = proxy._rules
    return {
        "mechanism": "namespace without uplink; one loopback port bridged to a fail-closed "
                     "front over srt's TLS-terminating proxy on the host",
        "tls_inspection": True,
        "fail_closed_front": True,
        "inner_host_check": True,
        "inner_sni_check": proxy.inner_sni_check,
        "proxy": {"package": SRT_PACKAGE, "version": SRT_VERSION, "integrity": SRT_INTEGRITY,
                  "tree_sha256": SRT_TREE_SHA256},
        "ca_sha256": proxy.ca_sha256,
        "allowlist_id": proxy.allowlist_id,
        "allowlist_digest": proxy.allowlist_digest,
        "allow": [f"{r['method']} https://{r['host']}{r.get('path', r.get('path_prefix', '') + '*')}"
                  for r in rules],
        "direct_egress": "no route",
    }


def cli_main(args) -> int:
    """``phase-loop seat-egress {status,install}`` (agent-harness#1170)."""
    if args.action == "install":
        try:
            install()
        except EgressLayerUnavailable as exc:
            print(json.dumps({"installed": False, "reason": str(exc)}, sort_keys=True))
            return 1
    reason = unavailable_reason()
    print(json.dumps({"available": reason is None, "reason": reason, "srt_version": SRT_VERSION,
                      "install_root": str(install_root()), "ca_dir": str(ca_dir())},
                     sort_keys=True))
    return 0 if reason is None else 1
