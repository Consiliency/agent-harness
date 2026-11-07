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
// Test-only: every TCP dial to port 443 from the proxy goes to the fixture upstream.
import net from 'node:net';
const port = Number(process.env.PHASE_LOOP_FIXTURE_UPSTREAM_PORT);
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const options = Array.isArray(args[0]) ? args[0][0] : args[0];
  if (options !== null && typeof options === 'object' && options.path === undefined
      && Number(options.port) === 443) {
    options.host = '127.0.0.1';
    options.port = port;
    delete options.lookup;
  }
  return connect.apply(this, args);
};
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
            lines = head.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            method, target, _version = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = {name.strip().lower(): value.strip() for name, _, value in
                       (line.partition(":") for line in lines[1:])}
            with self._lock:
                self.requests.append((getattr(tls, "phase_loop_sni", None), method, target,
                                      headers.get("host", "")))
            try:
                if "phase-loop-silence" in target:
                    tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                                b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                    tls.sendall(self._chunk(b"data: first\n\n"))
                    time.sleep(self.silence_s)
                    tls.sendall(self._chunk(b"data: last\n\n") + b"0\r\n\r\n")
                else:
                    body = f"fixture-upstream {method} {target}".encode()
                    tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                                + f"Content-Length: {len(body)}\r\n".encode()
                                + b"Connection: close\r\n\r\n" + body)
            except (OSError, ssl.SSLError):
                return

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

    def start(*, silence_s: float = 0.0):
        upstream = FixtureUpstream(tmp_path / "upstream", _probe_hosts(), silence_s=silence_s)
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
    signatures = {}
    for (label, _url), result in zip(targets, results):
        step = qualification.JailedStep(
            exit_code=result["exit_code"], timed_out=False,
            stdout=base64.b64decode(result["stdout"]))
        signatures[label] = qualification._curl_refusal(step)
    assert signatures == {label: "proxy_connect_refused" for label, _url in targets}
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

_MEASURE_RUNNER = r"""
import json, os, socket, subprocess, sys, time

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


@pytest.mark.host_seat_credentials
def test_measured_turn_completes_over_https_through_the_codex_proxy(tmp_path):
    if os.environ.get("PHASE_LOOP_CODEX_MEASURE") != "1":
        pytest.skip("set PHASE_LOOP_CODEX_MEASURE=1 on a developer host with a codex login")
    reason = seat_egress_proxy.unavailable_reason()
    cli = os.environ.get("PHASE_LOOP_CODEX_MEASURE_CLI", "")
    missing = [name for name in ("unshare", "ip", "socat") if shutil.which(name) is None]
    if reason is not None or missing or not os.path.isabs(cli) or not os.path.isfile(cli):
        pytest.fail(f"measurement prerequisites missing: {reason or ''} {missing} "
                    "PHASE_LOOP_CODEX_MEASURE_CLI must name the native codex image")
    auth_source = Path(os.environ.get("PHASE_LOOP_CODEX_MEASURE_AUTH")
                       or Path.home() / ".codex" / "auth.json")
    copy, kept_secrets = _measurement_copy(_private_file(auth_source))
    model = os.environ.get("PHASE_LOOP_CODEX_MEASURE_MODEL", "gpt-6-astra")
    work = tmp_path / "measure"
    for name in ("codex-home", "home", "tmp", "workspace", "tree", "out"):
        (work / name).mkdir(mode=0o700, parents=True)
    auth_copy = work / "codex-home" / "auth.json"
    with open(os.open(auth_copy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w",
              encoding="utf-8") as handle:
        json.dump(copy, handle)
    nonce = secrets.token_hex(16)
    (work / "tree" / "SENTINEL").write_text(nonce + "\n", encoding="ascii")
    (work / "prompt.txt").write_text(
        f"Use your shell tool to run `cat {work / 'tree' / 'SENTINEL'}`, then reply with "
        "exactly the text it printed and nothing else.\n", encoding="utf-8")
    last_message = work / "out" / "panel-codex.txt"
    argv = [cli, *(item for name in JAILED_CODEX_DISABLED_FEATURES
                   for item in ("--disable", name)),
            "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
            "--cd", str(work / "workspace"), "--skip-git-repo-check",
            "--sandbox", "danger-full-access",
            "-c", 'approval_policy="never"', "-c", 'cli_auth_credentials_store="file"',
            "--model", model, "-c", "model_reasoning_effort=low",
            "--output-last-message", str(last_message), "-"]
    runtime_path = Path(cli).resolve().parent.parent / "codex-path"
    started = time.monotonic()
    with seat_egress_proxy.start_proxy(allowlist_id="codex") as proxy:
        env = {
            "CODEX_HOME": str(work / "codex-home"), "HOME": str(work / "home"),
            "TMPDIR": str(work / "tmp"), "LANG": "C.UTF-8",
            "PATH": f"{runtime_path}:/usr/bin:/bin",
            "HTTPS_PROXY": proxy.proxy_url, "SSL_CERT_FILE": str(proxy.ca_cert),
            "CODEX_CA_CERTIFICATE": str(proxy.ca_cert),
        }
        spec = work / "spec.json"
        with open(os.open(spec, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w",
                  encoding="utf-8") as handle:
            json.dump({"front": proxy.socket, "ip": shutil.which("ip"),
                       "socat": shutil.which("socat"), "argv": argv, "env": env,
                       "cwd": str(work / "workspace"),
                       "prompt": str(work / "prompt.txt"), "stdout": str(work / "out" / "stdout"),
                       "stderr": str(work / "out" / "stderr"),
                       "version_out": str(work / "out" / "version"), "timeout_s": 600}, handle)
        start = seat_egress_proxy.fence(proxy, "start", "leg")
        done = subprocess.run(
            [shutil.which("unshare"), "--map-root-user", "--net", "--", sys.executable, "-I", "-c",
             _MEASURE_RUNNER, str(spec)],
            capture_output=True, timeout=720, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        end = seat_egress_proxy.fence(proxy, "end", "leg")
    duration_s = round(time.monotonic() - started, 1)
    stream = seat_egress_proxy.proxy_stream(proxy)
    stdout = (work / "out" / "stdout").read_bytes()
    kept = [stdout, (work / "out" / "stderr").read_bytes(),
            last_message.read_bytes() if last_message.exists() else b""]
    proxy_token = urllib.parse.urlsplit(proxy.proxy_url).password or proxy.proxy_url
    secret_in_output = any(value.encode() in blob for value in (*kept_secrets, proxy_token)
                           for blob in kept)
    tokens_changed = json.loads(auth_copy.read_text(encoding="utf-8")).get("tokens") \
        != copy["tokens"]
    events = _events(stdout)
    commands = [event["item"] for event in events
                if event.get("type") == "item.completed"
                and isinstance(event.get("item"), dict)
                and event["item"].get("type") == "command_execution"]
    completed = [item for item in commands if item.get("status") == "completed"
                 and item.get("exit_code") == 0 and item.get("aggregated_output")]
    window = [item for item in stream.windows if item.label == "leg"]
    requests: dict[tuple, int] = {}
    for event in (window[0].events if window else ()):
        key = (event.method, event.host, event.path, event.decision)
        requests[key] = requests.get(key, 0) + 1
    record = {
        "cli_version": (work / "out" / "version").read_text(encoding="utf-8").strip()
        if (work / "out" / "version").exists() else None,
        "allowlist_digest": proxy.allowlist_digest, "model": model, "effort": "low",
        "upgrades": "refused by srt inside every terminated tunnel",
        "exit_code": done.returncode, "duration_s": duration_s,
        "event_types": sorted({str(event.get("type")) for event in events}),
        "turn_completed": any(event.get("type") == "turn.completed" for event in events),
        "commands_completed": len(completed), "commands_failed": len(commands) - len(completed),
        "sentinel_quoted": any(nonce in str(item.get("aggregated_output")) for item in completed)
        and nonce.encode() in kept[2],
        "secret_in_output": secret_in_output, "tokens_changed": tokens_changed,
        "requests": [{"method": m, "host": h, "path": p, "decision": d, "count": c}
                     for (m, h, p, d), c in sorted(requests.items(), key=str)],
        "outside_events": len(stream.outside_events),
        "fences_acknowledged": bool(start.acknowledged and end.acknowledged),
    }
    _write_private_receipt("measured_turn", record)
    assert not secret_in_output, "codex_seat_token_in_output"
    assert not tokens_changed, "codex_seat_token_refreshed_in_jail"
    assert done.returncode == 0, record
    assert record["turn_completed"] and record["commands_completed"] >= 1, record
    assert record["sentinel_quoted"], record
    assert record["fences_acknowledged"] and stream.final and not stream.protocol_error
    assert record["outside_events"] == 0
    assert any(item["decision"] == "allow" for item in record["requests"]), record
