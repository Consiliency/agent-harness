"""SEATS CODEX SL-2: the Codex seat's egress allowlist and its probes (IF-0-CODEX-3,
EC-CODEX-3).

Four layers, from cheapest to live:

- the IF-0-CODEX-3 shape rules on the packaged file (offline);
- every ``probe_rows`` entry, path-entered through the real ``start_proxy`` and
  ``proxy.mjs`` over the pinned srt, against a fixture upstream on loopback. A test-only
  Node preload sends every port-443 dial to that fixture, so a request the proxy forwards
  is recorded there and a refused one leaves no trace (skips where the layer is absent);
- ``live_jail``: each refused row from a jailed tool command, under a fixture-registered
  profile on the real codex allowlist. Provider-free; with ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1``
  a missing prerequisite fails instead of skipping;
- ``measured_turn``: one real tooled codex turn through the proxy with upgrades refused,
  on the developer's own login. It runs only with ``PHASE_LOOP_CODEX_MEASURE=1``.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.parse

import pytest

from phase_loop_runtime import seat_egress_proxy, seat_jail
from phase_loop_runtime.seat_codex_cli_shape import JAILED_CODEX_DISABLED_FEATURES


GEMINI_BYTES_SHA256 = "7ed38bb15aee22b55c1952c6b6edddf6b54fc7fe0420c300097990592a16348f"
#: codex-cli 0.167.0 asks this endpoint for every token grant and refresh
#: (``https://auth.openai.com/oauth/token``, read from the binary, no request made).
CODEX_TOKEN_ENDPOINT_HOST = "auth.openai.com"
UNLISTED_PROBE_HOST = "seat-egress-unlisted.invalid"
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")

CODEX = seat_egress_proxy.allowlist_ref("codex")


def _document(name: str) -> dict:
    return json.loads(seat_egress_proxy._data_path(name).read_text(encoding="utf-8"))


def _other_allowlists() -> dict[str, dict]:
    directory = seat_egress_proxy._data_path("codex-allowlist.json").parent
    return {path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*-allowlist.json"))
            if path.name != "codex-allowlist.json"}


def _shape_problems(document: dict, others: dict[str, dict]) -> list[str]:
    """The IF-0-CODEX-3 rules, beyond what ``allowlist()`` already refuses."""
    problems = []
    if document.get("schema") != "phase_loop_seat_egress_allowlist.v1":
        problems.append("schema")
    if document.get("leg") != "codex":
        problems.append("leg")
    other_hosts = {rule["host"] for doc in others.values() for rule in doc.get("allow", [])}
    allow_hosts = set()
    for rule in document.get("allow", []):
        keys = set(rule)
        if keys not in ({"host", "port", "method", "path"},
                        {"host", "port", "method", "path_prefix"}):
            problems.append(f"keys {sorted(keys)}")
            continue
        host = rule["host"]
        allow_hosts.add(host)
        if "*" in host or not _HOST.fullmatch(host):
            problems.append(f"host {host}")
        if type(rule["port"]) is not int or rule["port"] != 443:
            problems.append(f"port {rule['port']!r}")
        if rule["method"] not in _METHODS:
            problems.append(f"method {rule['method']}")
        if "path_prefix" in rule and (rule["path_prefix"] == "/"
                                      or not rule["path_prefix"].startswith("/")):
            problems.append(f"path_prefix {rule['path_prefix']}")
        if "path" in rule and not rule["path"].startswith("/"):
            problems.append(f"path {rule['path']}")
        if host in other_hosts:
            problems.append(f"host {host} is listed by another seat")
    refused = document.get("measured_and_refused", [])
    if CODEX_TOKEN_ENDPOINT_HOST not in refused:
        problems.append("token endpoint not refused")
    if CODEX_TOKEN_ENDPOINT_HOST in allow_hosts:
        problems.append("token endpoint allowed")
    if allow_hosts & set(refused):
        problems.append("a host is both allowed and refused")
    return problems


# --------------------------------------------------------------------------------------
# IF-0-CODEX-3 shape rules (offline).
# --------------------------------------------------------------------------------------

def test_the_codex_allowlist_has_the_if_0_codex_3_shape():
    document = _document("codex-allowlist.json")
    assert _shape_problems(document, _other_allowlists()) == []
    assert document["allow"], "the allowlist must list the measured request set"


def test_the_codex_allowlist_loads_through_allowlist_ref():
    assert CODEX.id == "codex"
    document = _document("codex-allowlist.json")
    assert list(CODEX.request_set) == document["allow"]
    assert CODEX.content_digest == seat_egress_proxy._digest({
        key: document[key] for key in ("schema", "leg", "allow", "measured_and_refused")})
    rows = list(CODEX.probe_rows)
    allowed = [row for row in rows if row["decision"] == "allow"]
    refused = [row for row in rows if row["decision"] == "refuse"]
    assert [{k: v for k, v in row.items() if k != "decision"} for row in allowed] == \
        document["allow"]
    assert [row["host"] for row in refused] == [
        *document["measured_and_refused"], UNLISTED_PROBE_HOST]
    assert all(row["method"] == "CONNECT" and row["port"] == 443 for row in refused)


def test_only_allowlist_ref_names_the_codex_allowlist_file():
    package = Path(seat_egress_proxy.__file__).parent
    readers = [path.relative_to(package).as_posix()
               for path in sorted(package.rglob("*"))
               if path.suffix in {".py", ".mjs"} and path.is_file()
               and "codex-allowlist" in path.read_text(encoding="utf-8", errors="replace")]
    assert readers == []
    source = Path(seat_egress_proxy.__file__).read_text(encoding="utf-8")
    assert 'f"{allowlist_id}-allowlist.json"' in source


@pytest.mark.parametrize("mutation,problem", [
    (lambda d: d["allow"][0].update(host="*.chatgpt.com"), "host *.chatgpt.com"),
    (lambda d: d["allow"][0].update(port=80), "port 80"),
    (lambda d: d["allow"][0].update(port=True), "port True"),
    (lambda d: (d["allow"][0].pop("path", None), d["allow"][0].update(path_prefix="/")),
     "path_prefix /"),
    (lambda d: d["allow"][0].update(extra=1), "keys"),
    (lambda d: d["allow"].append({"host": "daily-cloudcode-pa.googleapis.com", "port": 443,
                                  "method": "POST", "path_prefix": "/v1internal:"}),
     "host daily-cloudcode-pa.googleapis.com is listed by another seat"),
    (lambda d: d["measured_and_refused"].remove(CODEX_TOKEN_ENDPOINT_HOST),
     "token endpoint not refused"),
    (lambda d: d["allow"].append({"host": CODEX_TOKEN_ENDPOINT_HOST, "port": 443,
                                  "method": "POST", "path": "/oauth/token"}),
     "token endpoint allowed"),
    (lambda d: d.update(leg="gemini"), "leg"),
], ids=["wildcard-host", "port-80", "port-bool", "slash-prefix", "extra-key", "gemini-host",
        "token-host-unrefused", "token-host-allowed", "leg"])
def test_each_shape_rule_refuses_its_mutant(mutation, problem):
    document = _document("codex-allowlist.json")
    mutation(document)
    problems = _shape_problems(document, _other_allowlists())
    assert any(item.startswith(problem) for item in problems), problems


def test_the_gemini_allowlist_bytes_are_unchanged():
    source = seat_egress_proxy._data_path("gemini-allowlist.json")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == GEMINI_BYTES_SHA256


def test_a_changed_codex_allowlist_moves_its_digest(tmp_path, monkeypatch):
    document = _document("codex-allowlist.json")
    document["measured_and_refused"].append("new.invalid")
    fixture = tmp_path / "codex-allowlist.json"
    fixture.write_text(json.dumps(document), encoding="utf-8")
    real = seat_egress_proxy._data_path
    monkeypatch.setattr(seat_egress_proxy, "_data_path",
                        lambda name: fixture if name == "codex-allowlist.json" else real(name))
    widened = seat_egress_proxy.allowlist_ref("codex")
    assert widened.content_digest != CODEX.content_digest
    assert widened.probe_rows != CODEX.probe_rows


# --------------------------------------------------------------------------------------
# Every probe row through the real proxy, against a fixture upstream.
# --------------------------------------------------------------------------------------

_DIAL_HOOK = r"""
// Test-only: every TCP dial to port 443 from the proxy goes to the fixture upstream. srt
// dials twice per upstream: a vetting probe through net.connect, then the request through
// https, whose agent opens its socket with tls.connect and `path: null`. Both entry points
// are redirected; a unix-socket dial (a string `path`) is left alone.
import net from 'node:net';
import tls from 'node:tls';
import { syncBuiltinESMExports } from 'node:module';
const port = Number(process.env.PHASE_LOOP_FIXTURE_UPSTREAM_PORT);
function redirect(options) {
  if (options !== null && typeof options === 'object' && options.path == null
      && options.socket == null && Number(options.port) === 443) {
    options.host = '127.0.0.1';
    options.port = port;
    delete options.lookup;
  }
}
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  redirect(Array.isArray(args[0]) ? args[0][0] : args[0]);
  return connect.apply(this, args);
};
const tlsConnect = tls.connect;
tls.connect = function (...args) {
  redirect(args[0]);
  return tlsConnect.apply(this, args);
};
syncBuiltinESMExports();
"""


def _layer_or_skip() -> None:
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        pytest.skip(f"the seat egress layer is not installed here ({reason})")
    # The pinned srt refuses to initialize without socat on Linux.
    for name in ("socat", "openssl"):
        if shutil.which(name, path="/usr/bin:/bin") is None:
            pytest.skip(f"{name} is unavailable")


def _openssl(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


class FixtureUpstream:
    """A TLS server on loopback that answers every request and records what reached it."""

    def __init__(self, directory: Path, hosts: list[str], *, silence_s: float = 0.0) -> None:
        directory.mkdir(mode=0o700)
        curve = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes")
        _openssl("req", "-x509", *curve, "-keyout", "ca.key", "-out", "ca.crt", "-days", "2",
                 "-subj", "/CN=phase-loop fixture upstream CA",
                 "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=directory)
        _openssl("req", "-new", *curve, "-keyout", "leaf.key", "-out", "leaf.csr",
                 "-subj", "/CN=phase-loop fixture upstream", cwd=directory)
        (directory / "leaf.ext").write_text(
            "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectAltName=" + ",".join(f"DNS:{host}" for host in hosts) + "\n",
            encoding="ascii")
        _openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
                 "-CAcreateserial", "-out", "leaf.crt", "-days", "2", "-extfile", "leaf.ext",
                 cwd=directory)
        self.ca = directory / "ca.crt"
        self.silence_s = silence_s
        self.connections = 0
        self.requests: list[tuple[str | None, str, str, str]] = []
        self._lock = threading.Lock()
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(directory / "leaf.crt", directory / "leaf.key")
        self._context.set_alpn_protocols(["http/1.1"])
        self._context.sni_callback = self._sni
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(0.2)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _sni(self, sock, name, _context):
        sock.phase_loop_sni = name

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except (TimeoutError, OSError):
                continue
            with self._lock:
                self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(10)
        try:
            tls = self._context.wrap_socket(conn, server_side=True)
        except (OSError, ssl.SSLError):
            conn.close()
            return
        with tls:
            try:
                head = b""
                while b"\r\n\r\n" not in head and len(head) < 65536:
                    chunk = tls.recv(4096)
                    if not chunk:
                        return
                    head += chunk
            except (OSError, ssl.SSLError):
                return
            head, _, rest = head.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _version = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = {name.strip().lower(): value.strip() for name, _, value in
                       (line.partition(":") for line in lines[1:])}
            with self._lock:
                self.requests.append((getattr(tls, "phase_loop_sni", None), method, target,
                                      headers.get("host", "")))
            try:
                self._drain_body(tls, headers, rest)
                self._respond(tls, method, target)
            except (OSError, ssl.SSLError):
                return

    @staticmethod
    def _drain_body(tls, headers: dict, rest: bytes) -> None:
        """Read the request body so the reply is not reset by unread bytes."""
        if headers.get("transfer-encoding", "").lower() == "chunked":
            while not rest.endswith(b"0\r\n\r\n") and len(rest) < (1 << 24):
                chunk = tls.recv(65536)
                if not chunk:
                    return
                rest += chunk
            return
        length = int(headers.get("content-length", "0") or 0)
        while len(rest) < length:
            chunk = tls.recv(min(65536, length - len(rest)))
            if not chunk:
                return
            rest += chunk

    def _respond(self, tls, method: str, target: str) -> None:
        if "phase-loop-silence" in target:
            tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                        b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
            tls.sendall(self._chunk(b"data: first\n\n"))
            time.sleep(self.silence_s)
            tls.sendall(self._chunk(b"data: last\n\n") + b"0\r\n\r\n")
            return
        self._reply(tls, 200, "text/plain", f"fixture-upstream {method} {target}".encode())

    @staticmethod
    def _reply(tls, status: int, content_type: str, body: bytes) -> None:
        reason = {200: "OK", 404: "Not Found"}.get(status, "OK")
        tls.sendall(f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n".encode()
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Connection: close\r\n\r\n" + body)

    @staticmethod
    def _chunk(data: bytes) -> bytes:
        return f"{len(data):x}\r\n".encode() + data + b"\r\n"

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._server.close()


def _probe_hosts() -> list[str]:
    hosts = {row["host"] for row in CODEX.probe_rows}
    for document in _other_allowlists().values():
        hosts.update(rule["host"] for rule in document.get("allow", []))
        hosts.update(host for host in document.get("measured_and_refused", [])
                     if "*" not in host)
    return sorted(hosts)


@pytest.fixture
def codex_front(tmp_path, monkeypatch):
    """The real ``start_proxy(allowlist_id="codex")``, with port-443 dials sent to a
    fixture upstream that trusts nothing but its own CA."""
    _layer_or_skip()

    def start(*, silence_s: float = 0.0, hosts=None, upstream_class=None):
        upstream = (upstream_class or FixtureUpstream)(
            tmp_path / "upstream", list(hosts or _probe_hosts()), silence_s=silence_s)
        hook = tmp_path / "dial-hook.mjs"
        hook.write_text(_DIAL_HOOK, encoding="utf-8")
        real_env = seat_egress_proxy._proxy_env

        def proxy_env(node, home):
            values = real_env(node, home)
            values.update({
                "NODE_OPTIONS": f"--import={hook.as_uri()}",
                "NODE_EXTRA_CA_CERTS": str(upstream.ca),
                "PHASE_LOOP_FIXTURE_UPSTREAM_PORT": str(upstream.port),
            })
            return values

        monkeypatch.setattr(seat_egress_proxy, "_proxy_env", proxy_env)
        return upstream

    holder: list[FixtureUpstream] = []

    def opened(**kwargs):
        upstream = start(**kwargs)
        holder.append(upstream)
        return upstream

    yield opened
    for upstream in holder:
        upstream.close()


def _authorization(proxy) -> bytes:
    token = urllib.parse.urlsplit(proxy.proxy_url).password
    assert token
    return base64.b64encode(f"srt:{token}".encode())


def _read_head(sock) -> bytes:
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 65536:
        chunk = sock.recv(4096)
        if not chunk:
            break
        head += chunk
    return head


def _exchange(proxy, host: str, request: bytes, *, timeout_s: float = 20.0
              ) -> tuple[bytes, bytes]:
    """``(CONNECT status line, decrypted reply)`` for one request inside one tunnel."""
    raw = socket.socket(socket.AF_UNIX)
    raw.settimeout(timeout_s)
    raw.connect(proxy.socket)
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n".encode()
                + b"Proxy-Authorization: Basic " + _authorization(proxy) + b"\r\n\r\n")
    status = _read_head(raw).split(b"\r\n", 1)[0]
    if not status.startswith(b"HTTP/1.1 200"):
        raw.close()
        return status, b""
    context = ssl.create_default_context(cafile=str(proxy.ca_cert))
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(request)
        reply = b""
        try:
            while True:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                reply += chunk
        except (ssl.SSLError, OSError):
            pass
    return status, reply


def _http(method: str, host: str, path: str, *headers: str) -> bytes:
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Content-Length: 0",
             "Connection: close", *headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def _row_id(row) -> str:
    return f"{row['decision']}-{row['method']}-{row['host']}"


def _allowed_path(row) -> str:
    return row["path"] if "path" in row else row["path_prefix"] + "phase-loop-probe"


@pytest.mark.parametrize("row", CODEX.probe_rows, ids=_row_id)
def test_every_codex_probe_row_through_the_real_proxy(row, codex_front):
    upstream = codex_front()
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        assert proxy.allowlist_digest == CODEX.content_digest
        if row["decision"] == "allow":
            path = _allowed_path(row)
            status, reply = _exchange(proxy, row["host"], _http(row["method"], row["host"], path))
            assert status.startswith(b"HTTP/1.1 200"), status
            assert reply.startswith(b"HTTP/1.1 200"), reply[:120]
            assert reply.endswith(f"fixture-upstream {row['method']} {path}".encode())
            assert upstream.requests == [(row["host"], row["method"], path, row["host"])]
        else:
            status, reply = _exchange(proxy, row["host"], _http("GET", row["host"], "/"))
            assert status.startswith(b"HTTP/1.1 403"), status
            assert reply == b""
            assert upstream.connections == 0 and upstream.requests == []


def _other_seat_rows() -> list[tuple[str, str, str, str]]:
    rows = []
    for name, document in _other_allowlists().items():
        rows.extend((name, rule["host"], rule["method"], _allowed_path(rule))
                    for rule in document.get("allow", []))
        rows.extend((name, host, "GET", "/") for host in document.get("measured_and_refused", [])
                    if "*" not in host)
    return rows


@pytest.mark.parametrize("source,host,method,path", _other_seat_rows(),
                         ids=lambda value: str(value))
def test_another_seats_hosts_do_not_reach_the_upstream(source, host, method, path, codex_front):
    upstream = codex_front()
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        status, reply = _exchange(proxy, host, _http(method, host, path))
    assert status.startswith(b"HTTP/1.1 403"), (source, status)
    assert reply == b""
    assert upstream.connections == 0 and upstream.requests == []


@pytest.mark.parametrize("row", CODEX.request_set,
                         ids=lambda row: f"{row['method']}-{row['host']}")
def test_an_allowed_tunnel_refuses_another_method_path_or_inner_host(row, codex_front):
    upstream = codex_front()
    path = _allowed_path(row)
    other_method = "DELETE" if row["method"] != "DELETE" else "PUT"
    outside = row["path"] + "-phase-loop-other" if "path" in row else "/phase-loop-outside"
    requests = {
        "method": _http(other_method, row["host"], path),
        "path": _http(row["method"], row["host"], outside),
        "inner-host": _http(row["method"], CODEX_TOKEN_ENDPOINT_HOST, path),
    }
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        replies = {label: _exchange(proxy, row["host"], request)
                   for label, request in requests.items()}
    for label, (status, reply) in replies.items():
        assert status.startswith(b"HTTP/1.1 200"), (label, status)
        assert reply.startswith(b"HTTP/1.1 403"), (label, reply[:120])
    assert upstream.requests == []


@pytest.mark.parametrize("row", CODEX.request_set,
                         ids=lambda row: f"{row['method']}-{row['host']}")
def test_an_upgrade_inside_an_allowed_tunnel_is_refused(row, codex_front):
    """srt refuses every upgrade inside a terminated tunnel, so a WebSocket handshake gets
    no reply at all, not the request filter's 403, and nothing reaches the upstream."""
    upstream = codex_front()
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    handshake = _http("GET", row["host"], _allowed_path(row), "Upgrade: websocket",
                      "Sec-WebSocket-Version: 13", f"Sec-WebSocket-Key: {key}")
    handshake = handshake.replace(b"Connection: close", b"Connection: Upgrade")
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        status, reply = _exchange(proxy, row["host"], handshake)
        control_status, control = _exchange(
            proxy, row["host"], _http(row["method"], row["host"], _allowed_path(row)))
    assert status.startswith(b"HTTP/1.1 200"), status
    assert reply == b"", reply[:120]
    assert control_status.startswith(b"HTTP/1.1 200") and control.startswith(b"HTTP/1.1 200")
    assert [request[1] for request in upstream.requests] == [row["method"]]


def _front_idle_ms() -> int:
    script = seat_egress_proxy._data_path("proxy.mjs").read_text(encoding="utf-8")
    match = re.search(r"const FRONT_IDLE_MS = config\.front_idle_ms \?\? (\d+);", script)
    assert match is not None
    return int(match.group(1))


def test_a_silent_upstream_past_the_front_idle_bound_keeps_its_stream(codex_front):
    """The production wrapper passes no idle bound, so the front runs on its default; a
    spliced stream whose upstream says nothing for longer than that bound stays open."""
    import inspect

    assert "front_idle_ms" not in inspect.getsource(seat_egress_proxy.start_proxy)
    bound_s = _front_idle_ms() / 1000.0
    silence_s = bound_s + 3.0
    upstream = codex_front(silence_s=silence_s)
    row = next(row for row in CODEX.request_set if row["method"] == "POST")
    path = _allowed_path(row) + "?phase-loop-silence=1"
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        started = time.monotonic()
        status, reply = _exchange(proxy, row["host"], _http("POST", row["host"], path),
                                  timeout_s=silence_s + 20.0)
        elapsed = time.monotonic() - started
    assert status.startswith(b"HTTP/1.1 200"), status
    assert b"data: first" in reply and b"data: last" in reply, reply[-200:]
    assert elapsed >= silence_s
    assert [request[2] for request in upstream.requests] == [path]


# --------------------------------------------------------------------------------------
# VL: each refused row from a jailed tool command under a fixture-registered profile.
# --------------------------------------------------------------------------------------

_JAILED_CURL = r"""
import base64, json, os, subprocess, sys

spec = json.loads(sys.argv[1])
env = dict(spec["env"])
env.update({name: os.environ[name] for name in spec["proxy_env"] if name in os.environ})
results = []
for argv in spec["steps"]:
    done = subprocess.run(argv, env=env, capture_output=True, timeout=60)
    results.append({"exit_code": done.returncode,
                    "stdout": base64.b64encode(done.stdout[:65536]).decode()})
print(json.dumps(results))
"""


def _refused_targets() -> list[tuple[str, str]]:
    targets = [(f"codex-refused:{row['host']}", f"https://{row['host']}/")
               for row in CODEX.probe_rows if row["decision"] == "refuse"]
    for name, host, method, path in _other_seat_rows():
        targets.append((f"{name}:{method}:{host}", f"https://{host}{path}"))
    return targets


def _live_jail_or_fail():
    if os.environ.get("PHASE_LOOP_REQUIRE_LIVE_JAIL") != "1":
        pytest.skip("set PHASE_LOOP_REQUIRE_LIVE_JAIL=1 on a jail-capable host")
    from phase_loop_runtime import sandbox_egress, seat_uid

    missing = []
    if not seat_uid.seat_uid_available():
        missing.append(seat_uid.PREREQUISITE)
    if not sandbox_egress.egress_isolation_available():
        missing.append("egress isolation unavailable")
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        missing.append(reason)
    if shutil.which("socat", path="/usr/bin:/bin") is None:
        missing.append("socat is not installed (the pinned srt needs it)")
    if missing:
        pytest.fail("live jail unavailable: " + "; ".join(missing))


def test_live_jail_codex_refused_rows_from_a_jailed_tool_command(
        tmp_path, monkeypatch, live_seat_attempt):
    _live_jail_or_fail()
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_egress, seat_profiles, seat_uid
    from phase_loop_runtime import seat_jail_qualification as qualification

    profile = dataclasses.replace(
        seat_profiles.profile_for("gemini"), leg="fixture", vendor="fixture",
        allowlist_id="codex", window=None)
    monkeypatch.setitem(seat_profiles._REGISTRY, "fixture", profile)
    targets = _refused_targets()
    steps = [["/usr/bin/curl", "-q", "--silent", "--show-error", "--max-time", "15",
              "--output", "/dev/null", "--dump-header", "-", "--write-out",
              qualification._CURL_WRITE_OUT, url] for _label, url in targets]
    spec = json.dumps({"env": dict(qualification.BRACKET_STEP_ENV), "steps": steps,
                       "proxy_env": sorted(pi._WINDOW_PROXY_ENV)})
    base = tmp_path / "vl"
    review = base / "seat" / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "README").write_text("codex allowlist probe tree\n", encoding="utf-8")
    seat_dir = base / "seat" / "dirs"
    seat_dir.mkdir(mode=0o700)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_egress_proxy.start_proxy(allowlist_id=profile.allowlist_id) as proxy:
        assert proxy.allowlist_digest == CODEX.content_digest
        config = seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
        pi._write_gemini_config(config, b"")
        certificate = seat_dir / "egress-ca.pem"
        shutil.copyfile(proxy.ca_cert, certificate)
        certificate.chmod(0o444)
        with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
                sandbox_egress.isolated_network(
                    timeout_s=900, required=True, seat_uid_map=True,
                    proxy_socket=proxy.socket,
                    proxy_port=seat_egress_proxy.SEAT_PROXY_PORT) as egress:
            token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
            holder = seat_uid.holder_pid_from_prefix(egress)
            jail = seat_jail.build_seat_jail(
                "fixture", seat_dir, Path("/usr/bin/python3"), tree=tree,
                bundle_memfd=seat_jail.memfd_with("b", b"B"),
                instructions_memfd=seat_jail.memfd_with("i", b"I"),
                token_fd=None, seat_ids=(n, n), gemini_config=config,
                egress_ca=certificate, egress_proxy=proxy.proxy_url)
            try:
                pi._require_canonical_jail(jail)
                start = seat_egress_proxy.fence(proxy, "start", "leg")
                done = subprocess.run(
                    [*pi._compose_seat_jail_prefix(jail), "/usr/bin/python3", "-I", "-c",
                     _JAILED_CURL, spec],
                    capture_output=True, text=True, timeout=900, pass_fds=jail.pass_fds,
                    env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
                end = seat_egress_proxy.fence(proxy, "end", "leg")
            finally:
                seat_jail.close_jail_fds(jail)
                for parent in (review, seat_dir):
                    seat_uid.teardown_in_h(holder, str(parent))
                pi._EGRESS_LAUNCH_PREFIX.reset(token)
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert done.returncode == 0, done.stderr[-400:]
    results = json.loads(done.stdout.strip().splitlines()[-1])
    assert len(results) == len(targets)
    signatures, observed = {}, {}
    for (label, _url), result in zip(targets, results):
        step = qualification.JailedStep(
            exit_code=result["exit_code"], timed_out=False,
            stdout=base64.b64decode(result["stdout"]))
        signatures[label] = qualification._curl_refusal(step)
        observed[label] = (step.exit_code, step.stdout.rpartition(b"PHASE_LOOP_CURL ")[2].strip())
    assert signatures == {label: "proxy_connect_refused" for label, _url in targets}, observed
    assert start.acknowledged and end.acknowledged
    assert stream.final and not stream.protocol_error
    window = [item for item in stream.windows if item.label == "leg"]
    assert len(window) == 1
    events = window[0].events
    assert len(events) == len(targets)
    assert all(event.method == "CONNECT" and event.decision == "deny" for event in events)
    _write_private_receipt("live_jail", {
        "host_class": "jail-capable seat host", "allowlist_digest": CODEX.content_digest,
        "profile": "fixture-registered (gemini-shaped, allowlist_id codex)",
        "rows": [{"label": label, "signature": signatures[label]} for label, _ in targets],
        "window_events": len(events), "window_allow_events": 0,
    })


def _write_private_receipt(kind: str, record: dict) -> None:
    """A metadata-only record for the lane's evidence, written only when asked for."""
    target = os.environ.get("PHASE_LOOP_CODEX_PROBE_RECORD")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600), "a",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, **record}, sort_keys=True) + "\n")


# --------------------------------------------------------------------------------------
# VM: one real tooled turn through the proxy, upgrades refused (developer's own login).
# --------------------------------------------------------------------------------------

#: An observation row: the proxy accepts the CONNECT, so the host is named in the event
#: stream, and refuses every request inside the tunnel (no upstream is dialed).
OBSERVE_ONLY_PATH = "/phase-loop-observe-only"
_OBSERVATION_DIR = Path.home() / ".local" / "state" / "agent-harness" / "codex-sl2"


def _observation_ref(path: Path, *, observe_token: bool = True):
    """Turn (a)'s private, uncommitted observation allowlist, bound like the packaged one.
    ``observe_token=False`` admits a private candidate set that leaves the token endpoint
    host unlisted (refused at CONNECT), for the provider-free sufficiency check."""
    from phase_loop_runtime.seat_route_contract import AllowlistRef

    resolved = path.resolve()
    if not resolved.is_relative_to(_OBSERVATION_DIR.resolve()):
        pytest.fail(f"the observation allowlist must live under {_OBSERVATION_DIR}")
    document = json.loads(_private_file(resolved))
    seat_egress_proxy._validate_allowlist_document("codex", document)
    rules = document["allow"]
    token_rows = [rule for rule in rules if rule["host"] == CODEX_TOKEN_ENDPOINT_HOST]
    if (observe_token and not token_rows) or any(
            rule.get("path") != OBSERVE_ONLY_PATH for rule in token_rows):
        pytest.fail("the token endpoint host may carry observe-only rows alone")
    if any(rule.get("path_prefix") == "/" or "*" in rule["host"] for rule in rules):
        pytest.fail("the observation allowlist has a wildcard host or a / prefix")
    bound = {key: document[key] for key in ("schema", "leg", "allow", "measured_and_refused")}
    return AllowlistRef(
        id="codex", content_digest=seat_egress_proxy._digest(bound),
        request_set=tuple(dict(rule) for rule in rules),
        probe_rows=seat_egress_proxy._probe_rows(rules, document["measured_and_refused"]))


def _observation_document() -> dict:
    document = _document("codex-allowlist.json")
    document["allow"] = [
        *document["allow"],
        {"host": CODEX_TOKEN_ENDPOINT_HOST, "port": 443, "method": "POST",
         "path": OBSERVE_ONLY_PATH},
    ]
    document["measured_and_refused"] = []
    return document


def _write_observation(directory: Path, document: dict, mode: int = 0o600) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "observation-allowlist.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(mode)
    return path


def test_the_observation_allowlist_loader_binds_and_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "_OBSERVATION_DIR", tmp_path / "private")
    good = _write_observation(tmp_path / "private", _observation_document())
    ref = _observation_ref(good)
    assert ref.id == "codex" and ref.content_digest != CODEX.content_digest
    assert any(rule["host"] == CODEX_TOKEN_ENDPOINT_HOST for rule in ref.request_set)
    opened = _observation_document()
    opened["allow"][-1]["path"] = "/oauth/token"
    for path in (_write_observation(tmp_path / "private" / "a", opened),
                 _write_observation(tmp_path / "elsewhere", _observation_document()),
                 _write_observation(tmp_path / "private" / "b", _observation_document(), 0o644)):
        with pytest.raises(pytest.fail.Exception):
            _observation_ref(path)


def test_an_observe_only_row_names_its_host_and_dials_nothing(codex_front, tmp_path,
                                                               monkeypatch):
    upstream = codex_front()
    monkeypatch.setattr(sys.modules[__name__], "_OBSERVATION_DIR", tmp_path / "private")
    ref = _observation_ref(_write_observation(tmp_path / "private", _observation_document()))
    real_ref = seat_egress_proxy.allowlist_ref
    monkeypatch.setattr(seat_egress_proxy, "allowlist_ref",
                        lambda allowlist_id: ref if allowlist_id == "codex"
                        else real_ref(allowlist_id))
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        assert proxy.allowlist_digest == ref.content_digest
        start = seat_egress_proxy.fence(proxy, "start", "leg")
        status, reply = _exchange(proxy, CODEX_TOKEN_ENDPOINT_HOST,
                                  _http("POST", CODEX_TOKEN_ENDPOINT_HOST, "/oauth/token"))
        end = seat_egress_proxy.fence(proxy, "end", "leg")
    assert status.startswith(b"HTTP/1.1 200") and reply.startswith(b"HTTP/1.1 403"), reply[:80]
    assert upstream.connections == 0 and upstream.requests == []
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert start.acknowledged and end.acknowledged and not stream.protocol_error
    events = [item for item in stream.windows if item.label == "leg"][0].events
    assert [(e.method, e.host, e.decision) for e in events] == [
        ("POST", CODEX_TOKEN_ENDPOINT_HOST, "deny")]


#
# Both live-CLI tests below run codex through ``_run_codex_turn``. The CLI's outputs are
# kept under a private run directory; the login copy lives only for the turn, is shredded
# in ``finally``, and its absence is asserted before any result is read.

_MEASURE_RUNNER = r"""
import json, os, socket, subprocess, sys, time

os.umask(0o077)
with open(sys.argv[1], encoding="utf-8") as handle:
    spec = json.load(handle)
subprocess.run([spec["ip"], "link", "set", "lo", "up"], check=True)
bridge = subprocess.Popen([spec["socat"], "TCP4-LISTEN:3128,bind=127.0.0.1,fork,reuseaddr",
                           "UNIX-CONNECT:" + spec["front"]])
deadline = time.monotonic() + 10
while True:
    try:
        socket.create_connection(("127.0.0.1", 3128), 1).close()
        break
    except OSError:
        if time.monotonic() > deadline:
            bridge.kill()
            raise SystemExit(70)
        time.sleep(0.05)
with open(spec["version_out"], "wb") as out:
    subprocess.run([spec["argv"][0], "--version"], stdout=out, stderr=subprocess.DEVNULL,
                   env=spec["env"], timeout=60)
try:
    with open(spec["prompt"], "rb") as prompt, open(spec["stdout"], "wb") as out, \
            open(spec["stderr"], "wb") as err:
        done = subprocess.run(spec["argv"], stdin=prompt, stdout=out, stderr=err,
                              env=spec["env"], cwd=spec["cwd"], timeout=spec["timeout_s"])
    code = done.returncode
except subprocess.TimeoutExpired:
    code = 124
finally:
    bridge.terminate()
    bridge.wait(5)
raise SystemExit(code)
"""


def _private_file(path: Path) -> bytes:
    info = os.lstat(path)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        pytest.fail("the developer's codex login file must be a private regular file")
    return path.read_bytes()


def _measurement_copy(raw: bytes) -> tuple[dict, tuple[str, ...]]:
    """The IF-0-CODEX-2 copy shape: a subscription login with an empty refresh token."""
    document = json.loads(raw)
    tokens = document.get("tokens")
    if (document.get("auth_mode") != "chatgpt" or document.get("OPENAI_API_KEY")
            or not isinstance(tokens, dict)):
        pytest.fail("the measured turn needs a subscription login (auth_mode chatgpt)")
    copy = {
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "last_refresh": document.get("last_refresh"),
        "tokens": {"access_token": tokens.get("access_token"),
                   "id_token": tokens.get("id_token"),
                   "account_id": tokens.get("account_id"), "refresh_token": ""},
    }
    secrets_kept = tuple(value for value in (tokens.get("access_token"), tokens.get("id_token"),
                                             tokens.get("refresh_token"))
                         if isinstance(value, str) and len(value) >= 16)
    return copy, secrets_kept


def _synthetic_login() -> dict:
    """A non-credential login in the subscription shape: unsigned tokens, fixture claims."""
    def token(claims: dict) -> str:
        def part(value: dict) -> str:
            raw = json.dumps(value, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}.c3ludGhldGlj"

    expires = int(time.time()) + 3600
    auth = {"chatgpt_plan_type": "pro", "chatgpt_account_id": "acct-synthetic",
            "chatgpt_user_id": "user-synthetic"}
    return {
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokens": {
            "id_token": token({"email": "fixture@example.invalid", "exp": expires,
                               "https://api.openai.com/auth": auth}),
            "access_token": token({"exp": expires, "https://api.openai.com/auth": auth}),
            "refresh_token": "", "account_id": "acct-synthetic",
        },
    }


def _shred_tree(root: Path) -> None:
    """Overwrite, then unlink, every file under ``root``; then remove the tree."""
    if not root.exists():
        return
    shred = shutil.which("shred", path="/usr/bin:/bin")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() and not path.is_symlink():
            if shred is not None:
                subprocess.run([shred, "-u", "-z", str(path)], check=False, timeout=60,
                               capture_output=True)
            if path.exists():
                size = path.stat().st_size
                with open(path, "r+b") as handle:
                    handle.write(b"\0" * size)
                    handle.flush()
                    os.fsync(handle.fileno())
                path.unlink()
    shutil.rmtree(root, ignore_errors=True)


def _private_run_dir(kind: str) -> Path:
    _OBSERVATION_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(_OBSERVATION_DIR, 0o700)
    run = _OBSERVATION_DIR / f"{kind}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-" \
        f"{secrets.token_hex(3)}"
    run.mkdir(mode=0o700)
    return run


def _mask(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}", "<jwt>", text)
    text = re.sub(r"[A-Za-z0-9_+/=-]{32,}", "<long>", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)
    text = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b", "<uuid>", text)
    return re.sub(r"\b\d{6,}\b", "<n>", text)


def _path_template(target: str) -> str:
    """The request path with the query dropped and id-like segments masked."""
    path = target.split("?", 1)[0]
    segments = []
    for segment in path.split("/"):
        if re.fullmatch(r"[0-9a-fA-F-]{8,}|\d{4,}|[A-Za-z0-9_-]{24,}", segment) or \
                re.fullmatch(r"(acct|user|org|thread|resp|conv)[-_][\w-]+", segment):
            segments.append("<id>")
        else:
            segments.append(segment)
    return "/".join(segments)


def _events(stream: bytes) -> list[dict]:
    events = []
    for line in stream.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _error_class(events: list[dict]) -> str | None:
    for event in events:
        if event.get("type") in ("error", "turn.failed"):
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            message = event.get("message") or error.get("message") or event.get("type")
            return _mask(str(message))[:200]
    return None


def _jailed_argv(cli: str, workspace: Path, last_message: Path, model: str) -> list[str]:
    return [cli, *(item for name in JAILED_CODEX_DISABLED_FEATURES
                   for item in ("--disable", name)),
            "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
            "--cd", str(workspace), "--skip-git-repo-check",
            "--sandbox", "danger-full-access",
            "-c", 'approval_policy="never"', "-c", 'cli_auth_credentials_store="file"',
            "--model", model, "-c", "model_reasoning_effort=low",
            "--output-last-message", str(last_message), "-"]


@dataclasses.dataclass
class TurnResult:
    exit_code: int
    duration_s: float
    start_acked: bool
    end_acked: bool
    tokens_changed: bool
    out: Path
    nonce: str


def _write_private_json(path: Path, value: dict) -> None:
    with open(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w",
              encoding="utf-8") as handle:
        json.dump(value, handle)


def _run_codex_turn(proxy, run: Path, *, cli: str, login: dict, model: str) -> TurnResult:
    """One codex exec turn in a namespace with no uplink, bridged to ``proxy``."""
    work = run / "work"
    out = run / "out"
    out.mkdir(mode=0o700)
    for name in ("codex-home", "home", "tmp", "workspace", "tree"):
        (work / name).mkdir(mode=0o700, parents=True)
    codex_home = work / "codex-home"
    nonce = secrets.token_hex(16)
    started = time.monotonic()
    start = end = None
    tokens_changed = True
    try:
        _write_private_json(codex_home / "auth.json", login)
        (work / "tree" / "SENTINEL").write_text(nonce + "\n", encoding="ascii")
        (work / "prompt.txt").write_text(
            f"Use your shell tool to run `cat {work / 'tree' / 'SENTINEL'}`, then reply with "
            "exactly the text it printed and nothing else.\n", encoding="utf-8")
        runtime_path = Path(cli).resolve().parent.parent / "codex-path"
        env = {
            "CODEX_HOME": str(codex_home), "HOME": str(work / "home"),
            "TMPDIR": str(work / "tmp"), "LANG": "C.UTF-8",
            "PATH": f"{runtime_path}:/usr/bin:/bin",
            "HTTPS_PROXY": proxy.proxy_url, "SSL_CERT_FILE": str(proxy.ca_cert),
            "CODEX_CA_CERTIFICATE": str(proxy.ca_cert),
        }
        _write_private_json(work / "spec.json", {
            "front": proxy.socket, "ip": shutil.which("ip"), "socat": shutil.which("socat"),
            "argv": _jailed_argv(cli, work / "workspace", out / "panel-codex.txt", model),
            "env": env, "cwd": str(work / "workspace"), "prompt": str(work / "prompt.txt"),
            "stdout": str(out / "stdout"), "stderr": str(out / "stderr"),
            "version_out": str(out / "version"), "timeout_s": 600})
        start = seat_egress_proxy.fence(proxy, "start", "leg")
        done = subprocess.run(
            [shutil.which("unshare"), "--map-root-user", "--net", "--", sys.executable, "-I",
             "-c", _MEASURE_RUNNER, str(work / "spec.json")],
            capture_output=True, timeout=720, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        end = seat_egress_proxy.fence(proxy, "end", "leg")
        observed = codex_home / "auth.json"
        tokens_changed = (not observed.exists()
                          or json.loads(observed.read_text(encoding="utf-8")).get("tokens")
                          != login["tokens"])
    finally:
        _shred_tree(codex_home)
        _shred_tree(work)
    assert not codex_home.exists() and not work.exists()
    assert not [path for path in run.rglob("auth.json")], "a login copy remains"
    return TurnResult(exit_code=done.returncode, duration_s=round(time.monotonic() - started, 1),
                      start_acked=bool(start and start.acknowledged),
                      end_acked=bool(end and end.acknowledged), tokens_changed=tokens_changed,
                      out=out, nonce=nonce)


def _turn_record(result: TurnResult, stream, kept_secrets, proxy_token: str) -> dict:
    stdout = (result.out / "stdout").read_bytes() if (result.out / "stdout").exists() else b""
    persisted = [path for path in result.out.rglob("*") if path.is_file()]
    secret_in_output = any(value.encode() in path.read_bytes()
                           for path in persisted for value in (*kept_secrets, proxy_token))
    last = result.out / "panel-codex.txt"
    events = _events(stdout)
    commands = [event["item"] for event in events
                if event.get("type") == "item.completed" and isinstance(event.get("item"), dict)
                and event["item"].get("type") == "command_execution"]
    completed = [item for item in commands if item.get("status") == "completed"
                 and item.get("exit_code") == 0 and item.get("aggregated_output")]
    window = [item for item in stream.windows if item.label == "leg"]
    requests: dict[tuple, int] = {}
    for event in (window[0].events if window else ()):
        key = (event.method, event.host, event.path, event.decision)
        requests[key] = requests.get(key, 0) + 1
    version = result.out / "version"
    return {
        "cli_version": version.read_text(encoding="utf-8").strip() if version.exists() else None,
        "exit_code": result.exit_code, "duration_s": result.duration_s,
        "event_types": sorted({str(event.get("type")) for event in events}),
        "turn_completed": any(event.get("type") == "turn.completed" for event in events),
        "error_class": _error_class(events),
        "commands_completed": len(completed), "commands_failed": len(commands) - len(completed),
        "sentinel_quoted": any(result.nonce in str(item.get("aggregated_output"))
                               for item in completed)
        and last.exists() and result.nonce.encode() in last.read_bytes(),
        "secret_in_output": secret_in_output, "tokens_changed": result.tokens_changed,
        "requests": [{"method": m, "host": h, "path": p, "decision": d, "count": c}
                     for (m, h, p, d), c in sorted(requests.items(), key=str)],
        "outside_events": len(stream.outside_events),
        "fences_acknowledged": result.start_acked and result.end_acked,
        "outputs": str(result.out),
    }


def _live_cli_or_fail() -> str:
    reason = seat_egress_proxy.unavailable_reason()
    cli = os.environ.get("PHASE_LOOP_CODEX_MEASURE_CLI", "")
    missing = [name for name in ("unshare", "ip", "socat") if shutil.which(name) is None]
    if reason is not None or missing or not os.path.isabs(cli) or not os.path.isfile(cli):
        pytest.fail(f"prerequisites missing: {reason or ''} {missing} "
                    "PHASE_LOOP_CODEX_MEASURE_CLI must name the native codex image")
    return cli


@pytest.mark.host_seat_credentials
def test_measured_turn_completes_over_https_through_the_codex_proxy(monkeypatch):
    """Turn (a) with ``PHASE_LOOP_CODEX_MEASURE_ALLOWLIST`` naming the private observation
    allowlist; turn (b) without it, through the committed ``codex-allowlist.json``."""
    if os.environ.get("PHASE_LOOP_CODEX_MEASURE") != "1":
        pytest.skip("set PHASE_LOOP_CODEX_MEASURE=1 on a developer host with a codex login")
    cli = _live_cli_or_fail()
    observation = os.environ.get("PHASE_LOOP_CODEX_MEASURE_ALLOWLIST")
    selected = _observation_ref(Path(observation)) if observation else CODEX
    if observation:
        real_ref = seat_egress_proxy.allowlist_ref
        monkeypatch.setattr(seat_egress_proxy, "allowlist_ref",
                            lambda allowlist_id: selected if allowlist_id == "codex"
                            else real_ref(allowlist_id))
    auth_source = Path(os.environ.get("PHASE_LOOP_CODEX_MEASURE_AUTH")
                       or Path.home() / ".codex" / "auth.json")
    copy, kept_secrets = _measurement_copy(_private_file(auth_source))
    model = os.environ.get("PHASE_LOOP_CODEX_MEASURE_MODEL", "gpt-6-astra")
    run = _private_run_dir("turn-a" if observation else "turn-b")
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        assert proxy.allowlist_digest == selected.content_digest
        result = _run_codex_turn(proxy, run, cli=cli, login=copy, model=model)
    stream = seat_egress_proxy.proxy_stream(proxy)
    proxy_token = urllib.parse.urlsplit(proxy.proxy_url).password or proxy.proxy_url
    record = {"turn": "a-observation" if observation else "b-committed", "model": model,
              "effort": "low", "allowlist_digest": proxy.allowlist_digest,
              "upgrades": "refused by srt inside every terminated tunnel",
              **_turn_record(result, stream, kept_secrets, proxy_token)}
    _write_private_receipt("measured_turn", record)
    assert not record["secret_in_output"], "codex_seat_token_in_output"
    assert not record["tokens_changed"], "codex_seat_token_refreshed_in_jail"
    assert record["exit_code"] == 0, record
    assert record["turn_completed"] and record["commands_completed"] >= 1, record
    assert record["sentinel_quoted"], record
    assert record["fences_acknowledged"] and stream.final and not stream.protocol_error
    assert record["outside_events"] == 0
    assert any(item["decision"] == "allow" for item in record["requests"]), record


# --------------------------------------------------------------------------------------
# Provider-free path discovery: the real CLI, a synthetic login, the fixture upstream.
# --------------------------------------------------------------------------------------

#: The hosts the discovery tunnels to the fixture upstream (every other host is refused).
DISCOVERY_HOSTS = ("chatgpt.com", CODEX_TOKEN_ENDPOINT_HOST, "ab.chatgpt.com", "api.openai.com",
                   "chat.openai.com", "persistent.oaistatic.com", "api.github.com",
                   "registry.npmjs.org", "openai.com")

_SSE_REPLY = "".join(
    f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n" for name, data in (
        ("response.created", {"type": "response.created", "response": {"id": "resp_fixture"}}),
        ("response.output_item.done", {
            "type": "response.output_item.done", "output_index": 0,
            "item": {"type": "message", "role": "assistant", "id": "msg_fixture",
                     "status": "completed",
                     "content": [{"type": "output_text", "text": "fixture reply"}]}}),
        ("response.completed", {
            "type": "response.completed",
            "response": {"id": "resp_fixture", "status": "completed",
                         "usage": {"input_tokens": 1, "output_tokens": 1,
                                   "total_tokens": 2}}}),
    )).encode()


#: The workspace-routing discovery reply (codex-rs backend-client ``AccountsCheckResponse``,
#: rust-v0.167.0): one account, the synthetic login's, with no backend or routing constraint.
_ACCOUNTS_CHECK_REPLY = json.dumps({
    "accounts": [{"id": "acct-synthetic", "workspace_backend_origin": "NO_CONSTRAINT",
                  "account_routing_override": "NO_CONSTRAINT", "structure": "personal"}],
    "account_ordering": ["acct-synthetic"], "default_account_id": "acct-synthetic",
}).encode()


class CodexFixtureUpstream(FixtureUpstream):
    """Minimal well-formed replies, so the CLI goes as far as it can: a models list, the
    workspace-routing account check, one streamed inference reply, and 404 otherwise."""

    def _respond(self, tls, method: str, target: str) -> None:
        path = target.split("?", 1)[0]
        if method == "GET" and path.endswith("/models"):
            self._reply(tls, 200, "application/json", b'{"models":[]}')
        elif method == "GET" and path.endswith("/accounts/check"):
            self._reply(tls, 200, "application/json", _ACCOUNTS_CHECK_REPLY)
        elif method == "POST" and path.startswith("/backend-api/codex/"):
            self._reply(tls, 200, "text/event-stream", _SSE_REPLY)
        else:
            self._reply(tls, 404, "application/json", b'{"detail":"Not Found"}')


def _discovery_ref():
    from phase_loop_runtime.seat_route_contract import AllowlistRef

    rules = [{"host": host, "port": 443, "method": method, "path_prefix": "/"}
             for host in DISCOVERY_HOSTS
             for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")]
    bound = {"schema": "phase_loop_seat_egress_allowlist.v1", "leg": "codex", "allow": rules,
             "measured_and_refused": []}
    return AllowlistRef(id="codex", content_digest=seat_egress_proxy._digest(bound),
                        request_set=tuple(rules),
                        probe_rows=seat_egress_proxy._probe_rows(rules, []))


def _process_tree(root: int) -> set[int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                parents[int(entry.name)] = int(fields[1])
            except (OSError, IndexError, ValueError):
                continue
    tree, frontier = {root}, [root]
    while frontier:
        parent = frontier.pop()
        for pid, ppid in parents.items():
            if ppid == parent and pid not in tree:
                tree.add(pid)
                frontier.append(pid)
    return tree


def _remote_endpoints(pids: set[int]) -> set[str]:
    """Every TCP peer of the processes' sockets, as ``ip:port``."""
    peers: set[str] = set()
    for pid in pids:
        try:
            inodes = {os.readlink(fd)[8:-1] for fd in Path(f"/proc/{pid}/fd").iterdir()
                      if os.readlink(fd).startswith("socket:[")}
        except OSError:
            continue
        for table, width in (("tcp", 8), ("tcp6", 32)):
            try:
                rows = Path(f"/proc/{pid}/net/{table}").read_text().splitlines()[1:]
            except OSError:
                continue
            for row in rows:
                fields = row.split()
                if len(fields) < 10 or fields[9] not in inodes:
                    continue
                address, port = fields[2].split(":")
                if width == 8:
                    peer = socket.inet_ntop(socket.AF_INET, bytes.fromhex(address)[::-1])
                else:
                    raw = bytes.fromhex(address)
                    peer = socket.inet_ntop(socket.AF_INET6, b"".join(
                        raw[i:i + 4][::-1] for i in range(0, 16, 4)))
                peers.add(f"{peer}:{int(port, 16)}")
    return peers


_LOOPBACK_PEERS = re.compile(r"(127\.0\.0\.1|::1|::ffff:127\.0\.0\.1|0\.0\.0\.0|::):\d+")


def test_provider_free_path_discovery_through_the_fixture_upstream(codex_front, monkeypatch):
    """The real CLI on a synthetic login: every request it makes reaches the loopback
    fixture upstream, which records its exact method and path. No connection leaves
    loopback: the proxy's event stream and a socket watch on its process tree agree."""
    if os.environ.get("PHASE_LOOP_CODEX_DISCOVER") != "1":
        pytest.skip("set PHASE_LOOP_CODEX_DISCOVER=1 with PHASE_LOOP_CODEX_MEASURE_CLI")
    cli = _live_cli_or_fail()
    upstream = codex_front(hosts=DISCOVERY_HOSTS, upstream_class=CodexFixtureUpstream)
    # PHASE_LOOP_CODEX_DISCOVER_ALLOWLIST names a private candidate set instead: the proxy
    # then refuses every other request, as production would, against the same fixture.
    candidate = os.environ.get("PHASE_LOOP_CODEX_DISCOVER_ALLOWLIST")
    ref = _observation_ref(Path(candidate), observe_token=False) if candidate \
        else _discovery_ref()
    real_ref = seat_egress_proxy.allowlist_ref
    monkeypatch.setattr(seat_egress_proxy, "allowlist_ref",
                        lambda allowlist_id: ref if allowlist_id == "codex"
                        else real_ref(allowlist_id))
    login = _synthetic_login()
    run = _private_run_dir("discovery")
    peers: set[str] = set()
    stop = threading.Event()
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        assert proxy.allowlist_digest == ref.content_digest

        def watch():
            while not stop.is_set():
                peers.update(_remote_endpoints(_process_tree(proxy.process.pid)))
                time.sleep(0.05)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            result = _run_codex_turn(proxy, run, cli=cli, login=login, model="gpt-6-astra")
        finally:
            stop.set()
            watcher.join(timeout=5)
    stream = seat_egress_proxy.proxy_stream(proxy)
    record = _turn_record(result, stream, (), urllib.parse.urlsplit(proxy.proxy_url).password)
    paths: dict[tuple, int] = {}
    for sni, method, target, host in upstream.requests:
        key = (sni or host, method, _path_template(target))
        paths[key] = paths.get(key, 0) + 1
    off_loopback = sorted(peer for peer in peers if not _LOOPBACK_PEERS.fullmatch(peer))
    discovery = {
        "login": "synthetic (no credential)", "upstream": "loopback fixture",
        "fixture_requests": [{"host": h, "method": m, "path": p, "count": c}
                             for (h, m, p), c in sorted(paths.items())],
        "fixture_connections": upstream.connections,
        "proxy_peers": sorted(peers), "off_loopback_peers": off_loopback,
        **record,
    }
    _write_private_receipt("path_discovery", discovery)
    (run / "discovery.json").write_text(json.dumps(discovery, indent=1), encoding="utf-8")
    os.chmod(run / "discovery.json", 0o600)
    assert off_loopback == [], off_loopback
    assert record["outside_events"] == 0 and record["fences_acknowledged"]
    assert upstream.requests, "the CLI made no request through the proxy"


def test_the_probe_evidence_names_the_committed_allowlist():
    """The SL-2.3 record (evidence id ``codex-unlisted-endpoint``) binds the committed rows:
    a changed allowlist leaves it stale until it is measured again. Repo-only."""
    record = (Path(__file__).resolve().parents[2] / "plans" / "evidence" / "seat-codex"
              / "allowlist-probes.json")
    if not record.is_file():
        pytest.skip("repo-only evidence is absent on an installed wheel")
    document = json.loads(record.read_text(encoding="utf-8"))
    assert document["evidence_id"] == "codex-unlisted-endpoint"
    assert document["allowlist"]["content_digest"] == CODEX.content_digest
    committed = [turn for turn in document["vm"]["turns"] if turn["turn"] == "b-committed"]
    assert len(committed) == 1 and committed[0]["allowlist_digest"] == CODEX.content_digest
    assert committed[0]["turn_completed"] and committed[0]["commands_completed"] >= 1
    allowed = {(item["method"], item["host"], item["path"])
               for item in committed[0]["requests"] if item["decision"] == "allow"}
    rows = {(rule["method"], rule["host"], rule.get("path", rule.get("path_prefix", "") + "*"))
            for rule in CODEX.request_set}
    assert allowed == rows
    assert document["vl"]["status"] in {"pending", "pass"}
