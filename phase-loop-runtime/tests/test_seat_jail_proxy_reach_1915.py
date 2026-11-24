"""A jailed seat reaches its egress proxy, and nothing else (agent-harness#1915).

Live only: with ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1`` on a jail-capable host a missing
prerequisite fails instead of skipping. One jailed process, after the seat-uid drop:

- runs outside the uid-drop AppArmor profile (`seat_jail_apparmor`), so the hand-back took it
  back to the confinement every other bwrap child has;
- reaches the proxy bridge on its loopback port, and the proxy answers there: a listed
  host is admitted and an unlisted one refused;
- reaches nothing else: a listener on the host's own address, which the host itself can
  reach, gets no connection, and the seat's other loopback ports refuse. Each of those
  fails with a network error (no route, refused), never a refused socket.

The proxy runs a fixture allowlist of ``.invalid`` hosts, and the admitted tunnel is closed
before any byte follows the CONNECT, so no request leaves the host. On a Ubuntu 24.04+/26.04
host this needs the current override from ``python3 -m phase_loop_runtime.seat_jail_apparmor``
installed by an administrator.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import socket
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from phase_loop_runtime import seat_egress_proxy, seat_jail
from phase_loop_runtime.seat_route_contract import AllowlistRef

LISTED = "fixture-reach.invalid"
UNLISTED = "not-listed.invalid"
UID_DROP_PROFILE = "phase_loop_seat_uid_drop"
#: How a destination with no route from the seat fails: never EACCES or EPERM.
NETWORK_ERRORS = frozenset({"ENETUNREACH", "EHOSTUNREACH", "ECONNREFUSED", "ETIMEDOUT",
                            "EADDRNOTAVAIL"})

_JAILED_PROBE = r"""
import base64, errno, json, os, socket, sys, urllib.parse

spec = json.loads(sys.argv[1])


def outcome(exc):
    if isinstance(exc, TimeoutError) and not exc.errno:
        return "ETIMEDOUT"
    return errno.errorcode.get(exc.errno, str(exc.errno)) if exc.errno else type(exc).__name__


def label():
    for path in ("/proc/self/attr/apparmor/current", "/proc/self/attr/current"):
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read().strip("\0\n ")
        except OSError:
            continue
    return None


def connect(family, address):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(address)
            return "connected"
    except OSError as exc:
        return outcome(exc)


def through_proxy(host):
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    basic = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
    try:
        with socket.create_connection((proxy.hostname, proxy.port), timeout=10) as client:
            client.sendall((f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                            f"Proxy-Authorization: Basic {basic}\r\n\r\n").encode())
            return client.recv(128).split(b"\r\n", 1)[0].decode("latin-1")
    except OSError as exc:
        return outcome(exc)


print(json.dumps({
    "label": label(),
    "listed": through_proxy(spec["listed"]),
    "unlisted": through_proxy(spec["unlisted"]),
    "host_address": connect(socket.AF_INET, (spec["host_address"], spec["host_port"])),
    "loopback_other_port": connect(socket.AF_INET, ("127.0.0.1", spec["other_port"])),
    "inet6_loopback": connect(socket.AF_INET6, ("::1", spec["other_port"])),
}))
"""


def _fixture_ref(allowlist_id: str) -> AllowlistRef:
    return AllowlistRef(
        id=allowlist_id, content_digest=hashlib.sha256(allowlist_id.encode()).hexdigest(),
        request_set=({"host": LISTED, "port": 443, "method": "GET", "path": "/"},),
        probe_rows=())


def _host_address() -> str | None:
    """This host's own outbound IPv4 address (a UDP connect sends no packet)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))
        except OSError:
            return None
        address = probe.getsockname()[0]
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def _live_jail_or_fail() -> str:
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
    address = _host_address()
    if address is None:
        missing.append("this host has no non-loopback IPv4 address for the control listener")
    if missing:
        pytest.fail("live jail unavailable: " + "; ".join(missing))
    assert address is not None
    return address


def test_live_jail_seat_reaches_its_proxy_and_nothing_else(
        tmp_path, monkeypatch, live_seat_attempt):
    host_address = _live_jail_or_fail()
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_egress, seat_profiles, seat_uid

    monkeypatch.setattr(seat_egress_proxy, "allowlist_ref", _fixture_ref)
    profile = dataclasses.replace(
        seat_profiles.profile_for("gemini"), leg="fixture", vendor="fixture",
        allowlist_id="fixture-reach", window=None)
    monkeypatch.setitem(seat_profiles._REGISTRY, "fixture", profile)
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        other_port = unused.getsockname()[1]
    assert other_port != seat_egress_proxy.SEAT_PROXY_PORT
    listener = socket.create_server((host_address, 0))
    listener.settimeout(5)
    host_port = listener.getsockname()[1]
    # Positive control: the host itself reaches the listener, so a refusal from the seat is
    # the seat's network, not an unreachable address.
    with socket.create_connection((host_address, host_port), timeout=5):
        accepted, _peer = listener.accept()
        accepted.close()
    spec = json.dumps({"listed": LISTED, "unlisted": UNLISTED, "host_address": host_address,
                       "host_port": host_port, "other_port": other_port})
    base = tmp_path / "reach"
    review = base / "seat" / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "README").write_text("proxy reach probe tree\n", encoding="utf-8")
    seat_dir = base / "seat" / "dirs"
    seat_dir.mkdir(mode=0o700)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    try:
        with seat_egress_proxy.start_proxy(allowlist_id=profile.allowlist_id) as proxy:
            token = urllib.parse.urlsplit(proxy.proxy_url).password or proxy.proxy_url
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
                prefix_token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
                holder = seat_uid.holder_pid_from_prefix(egress)
                jail = seat_jail.build_seat_jail(
                    "fixture", seat_dir, Path("/usr/bin/python3"), tree=tree,
                    bundle_memfd=seat_jail.memfd_with("b", b"B"),
                    instructions_memfd=seat_jail.memfd_with("i", b"I"),
                    token_fd=None, seat_ids=(n, n), gemini_config=config,
                    egress_ca=certificate, egress_proxy=proxy.proxy_url)
                try:
                    pi._require_canonical_jail(jail)
                    done = subprocess.run(
                        [*pi._compose_seat_jail_prefix(jail), "/usr/bin/python3", "-I", "-c",
                         _JAILED_PROBE, spec],
                        capture_output=True, text=True, timeout=900, pass_fds=jail.pass_fds,
                        env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
                finally:
                    seat_jail.close_jail_fds(jail)
                    for parent in (review, seat_dir):
                        seat_uid.teardown_in_h(holder, str(parent))
                    pi._EGRESS_LAUNCH_PREFIX.reset(prefix_token)
        listener.settimeout(1)
        try:
            stray, _peer = listener.accept()
        except (BlockingIOError, TimeoutError, socket.timeout):
            stray = None
        if stray is not None:
            stray.close()
    finally:
        listener.close()
    assert token not in done.stdout and token not in done.stderr
    assert done.returncode == 0, done.stderr[-400:]
    results = json.loads(done.stdout.strip().splitlines()[-1])
    assert UID_DROP_PROFILE not in (results["label"] or ""), results
    assert results["listed"].startswith("HTTP/1.1 200"), results
    assert results["unlisted"].startswith("HTTP/1.1 403"), results
    assert results["host_address"] in NETWORK_ERRORS, results
    assert stray is None, "the host listener received a connection from the seat"
    assert results["loopback_other_port"] == "ECONNREFUSED", results
    # A host without IPv6 in the seat's namespace has no such family at all.
    assert results["inet6_loopback"] in NETWORK_ERRORS | {"EAFNOSUPPORT"}, results


@pytest.mark.parametrize("provider", ["codex", "grok", "claude"])
def test_private_front_mode_is_gemini_only(provider, monkeypatch):
    monkeypatch.setattr(seat_egress_proxy, "_node",
                        lambda: pytest.fail("unsupported mode reached dispatch"))
    with pytest.raises(ValueError, match="reserved for jailed Gemini"):
        with seat_egress_proxy.start_private_gemini_proxy(allowlist_id=provider):
            pytest.fail("unsupported mode started")


def test_private_front_request_matrix_without_sockets(tmp_path):
    """Run the actual front and request filter against an in-memory SRT transport."""
    from test_gemini_seat_egress_1170 import _client_hello

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to run the front")
    config = tmp_path / "proxy.json"
    config.write_text(json.dumps({"allow": list(_fixture_ref("gemini").request_set),
                                  "inner_sni_check": True, "private_gemini": True}))
    srt = tmp_path / "srt.mjs"
    srt.write_text("""
export const SandboxManager = {
  initialize: options => { globalThis.filter = options.network.filterRequest; },
  getMitmCA: () => ({secureContexts: {
    get: name => { if (name !== 'fixture-reach.invalid') throw new Error(); },
  }}),
  getLinuxHttpSocketPath: () => '/mock-srt.sock',
  getProxyAuthToken: () => 'fixture-session',
  reset: () => {},
};
""")
    run = tmp_path / "front-test.mjs"
    run.write_text(r"""
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import net from 'node:net';
import { pathToFileURL } from 'node:url';

const [frontPath, srtPath, configPath, helloHex, wrongHex] = process.argv.slice(2);
process.argv = [process.argv[0], frontPath, pathToFileURL(srtPath).href, configPath];
fs.mkdtempSync = () => '/mock-private-front';

class Socket extends EventEmitter {
  writes = [];
  write(data) { this.writes.push(data); }
  end(data) { this.write(data); this.destroy(); }
  destroy() { this.emit('close'); }
  pipe() {}
}

let accept;
const upstream = [];
net.createServer = handler => {
  accept = handler;
  return { on() {}, listen(path, ready) { ready(); }, unref() {}, close() {} };
};
net.connect = ({path}) => {
  assert.equal(path, '/mock-srt.sock');
  const socket = new Socket();
  upstream.push(socket);
  return socket;
};
syncBuiltinESMExports();
const events = [];
process.stdout.write = line => {
  events.push(JSON.parse(line));
  return true;
};

await import(pathToFileURL(frontPath));
assert.deepEqual(events.shift(), {
  socket: '/mock-private-front/front.sock', token: 'fixture-session',
  tls_inspection: true, inner_sni_check: true, fail_closed_front: true,
});

function request(host, headers = '') {
  const client = new Socket();
  accept(client);
  client.emit('data', Buffer.from('CONNECT ' + host + ':443 HTTP/1.1\r\n' + headers + '\r\n'));
  return client;
}
const host = 'fixture-reach.invalid';
const auth = 'Basic ' + Buffer.from('srt:fixture-session').toString('base64');
for (const header of ['Proxy-Authorization: Basic c3J0Og==\r\n',
                      'Proxy-Authorization:\r\n',
                      'Proxy-Authorization: ' + auth + '\r\nProxy-Authorization: wrong\r\n']) {
  assert.match(request(host, header).writes[0], /^HTTP\/1.1 407/);
}
assert.equal(upstream.length, 0);
assert.deepEqual(events, []);

for (const header of ['', 'Proxy-Authorization: ' + auth + '\r\n']) {
  const client = request(host, header);
  assert.match(client.writes[0], /^HTTP\/1.1 200/);
  client.emit('data', Buffer.from(helloHex, 'hex'));
  const socket = upstream.pop();
  assert.ok(socket);
  socket.emit('connect');
  assert.equal(socket.writes[0], 'CONNECT ' + host + ':443 HTTP/1.1\r\nHost: ' + host
               + ':443\r\nProxy-Authorization: ' + auth + '\r\n\r\n');
  socket.emit('data', Buffer.from('HTTP/1.1 200 Connection Established\r\n\r\n'));
  assert.deepEqual(socket.writes[1], Buffer.from(helloHex, 'hex'));
}

assert.match(request('not-listed.invalid').writes[0], /^HTTP\/1.1 403/);
for (const hello of [wrongHex, '150303000401000000']) {
  const client = request(host);
  assert.match(client.writes[0], /^HTTP\/1.1 200/);
  client.emit('data', Buffer.from(hello, 'hex'));
  assert.equal(upstream.length, 0);
}
assert.deepEqual(events.map(event => event.decision), ['deny', 'deny', 'deny']);

for (const [method, path, innerHost, decision] of [
  ['GET', '/', host, 'allow'],
  ['GET', '/forbidden', host, 'deny'],
  ['POST', '/', host, 'deny'],
  ['GET', '/', 'not-listed.invalid', 'deny'],
]) {
  const result = await globalThis.filter(new Request('https://' + host + path,
    {method, headers: {'Host': innerHost}}));
  assert.equal(result.action, decision);
}
assert.deepEqual(events.slice(3).map(event => event.decision), ['allow', 'deny', 'deny', 'deny']);

fs.writeFileSync(configPath, JSON.stringify({allow: [], private_gemini: true}));
await import(pathToFileURL(frontPath).href + '?refuse-all');
assert.match(request(host).writes[0], /^HTTP\/1.1 403/);
assert.equal(upstream.length, 0);

fs.writeFileSync(configPath, JSON.stringify({allow: [{host, port: 443, method: 'GET', path: '/'}]}));
await import(pathToFileURL(frontPath).href + '?default');
assert.match(request(host).writes[0], /^HTTP\/1.1 407/);
assert.match(request(host, 'Proxy-Authorization: ' + auth + '\r\n').writes[0], /^HTTP\/1.1 200/);
process.exit(0);
""")
    done = subprocess.run(
        [node, str(run), str(seat_egress_proxy._data_path("proxy.mjs")), str(srt), str(config),
         _client_hello(LISTED.encode(), 3).hex(), _client_hello(UNLISTED.encode(), 3).hex()],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
    )
    assert done.returncode == 0, done.stderr
