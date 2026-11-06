"""TEAMHOST Gemini admission-key and fail-closed-front proofs (agent-harness#1820)."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_provenance as prov
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker
from phase_loop_runtime import seat_egress_proxy


MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
HELP = b"synthetic help\n"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(gh, "_local_capabilities", lambda: None)
    monkeypatch.setattr(q, "_LAST_KNOWN_GOOD_PROVIDER", None)
    q._HELP_MEMO.clear()
    q._REQUALIFIED.clear()


def _subject(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def _seed(image: bytes, *, version="9.9.9") -> q.Store:
    digest = sha256(image).hexdigest()
    store = q.Store()
    store.create()
    asset = SimpleNamespace(name=HOST.asset, version=version, digest="sha256:" + "0" * 64)
    key = q.agy_profile_digest()
    store.put_provenance(SimpleNamespace(image_sha256=digest, platform=HOST.name, asset=asset), key)
    store.put_qualified(digest, sha256(HELP).hexdigest(), HOST, key, version)
    return store


def test_profile_digest_changes_only_with_owned_profile_or_operations(monkeypatch):
    original = q.agy_profile_digest()
    monkeypatch.setattr(q, "__version__", "999.0")
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {"f" * 64: "e" * 64})
    assert q.agy_profile_digest() == original
    with monkeypatch.context() as changed:
        changed.setattr(gh, "PROFILE_ID", "different-owned-profile")
        assert q.agy_profile_digest() != original
    operation = q.OPERATIONS_CONTRACT[0]._replace(pass_predicate_id="different-predicate")
    monkeypatch.setattr(q, "OPERATIONS_CONTRACT", (operation, *q.OPERATIONS_CONTRACT[1:]))
    assert q.agy_profile_digest() != original


def test_qualification_rendering_is_driven_by_the_operations_contract():
    model = "gemini-synthetic"
    actual = panel_invoker._brokered_gemini_command(
        model=model, deadline_s=1, monitoring_policy="heartbeat_only")
    actual[0] = gh.PRIVATE_HOME + "/agy"
    assert actual == q.render_operation_argv("completion", model)
    assert q._operation("completion").env_names == (
        "HOME", "LANG", "LC_ALL", "LC_CTYPE", "NO_COLOR", "PATH", "TERM",
        "XDG_CONFIG_HOME",
    )


def test_record_survives_version_and_release_set_edits(tmp_path, monkeypatch):
    image = b"#!/bin/sh\necho qualified\n"
    path = _subject(tmp_path, "agy", image)
    store = _seed(image)
    before = store.get_provenance(sha256(image).hexdigest(), HOST, q.agy_profile_digest())
    monkeypatch.setattr(q, "__version__", "999.0")
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {"f" * 64: "e" * 64})
    monkeypatch.setattr(q, "_run_help", lambda *_: HELP)
    admission = gh.admit({"PATH": str(tmp_path)}, subject_path=path)
    try:
        assert admission.admission_class == "locally_qualified"
        assert admission.source == "subject"
    finally:
        admission.close()
    assert before["written_under"] != q.__version__


def test_last_known_good_is_opt_in_and_admits_its_own_verified_bytes(tmp_path, monkeypatch):
    subject = _subject(tmp_path, "agy-new", b"#!/bin/sh\necho unqualified\n")
    lkg_bytes = b"#!/bin/sh\necho last-known-good\n"
    _seed(lkg_bytes)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: True)
    monkeypatch.setattr(q, "_run_help", lambda *_: HELP)
    assert q.last_known_good() is None
    q.register_last_known_good(lambda: gh.VerifiedImage.from_bytes(lkg_bytes, tmp_path / "agy-lkg"))
    with pytest.raises(RuntimeError, match="already registered"):
        q.register_last_known_good(lambda: None)
    admission = gh.admit({"PATH": str(tmp_path)}, subject_path=subject)
    try:
        assert (admission.source, admission.admission_class) == ("lkg", "locally_qualified")
        assert admission.image.sha256 == sha256(lkg_bytes).hexdigest()
    finally:
        admission.close()


def test_read_only_record_and_verdict_checks_spawn_nothing(tmp_path, monkeypatch):
    image = b"#!/bin/sh\necho qualified\n"
    path = _subject(tmp_path, "agy", image)
    _seed(image)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned"))
    assert q.has_record(sha256(image).hexdigest())
    assert q.admission_verdict({}, path, execute=False) == q.AgyVerdict(
        "unknown", None, "launch_measurement")


def test_requalify_once_calls_ensure_once_for_one_store_key_image(tmp_path, monkeypatch):
    image = b"#!/bin/sh\necho candidate\n"
    path = _subject(tmp_path, "agy", image)
    env = {"PATH": str(tmp_path)}
    calls = []

    def admission():
        return gh.Admission(gh.VerifiedImage.from_bytes(image, path), sha256(HELP).hexdigest(),
                            "locally_qualified", path)

    monkeypatch.setattr(q, "ensure_admitted", lambda *a, **k: calls.append("ensure") or admission())
    monkeypatch.setattr(gh, "admit", lambda *a, **k: calls.append("lookup") or admission())
    first = q.requalify_once(env)
    second = q.requalify_once(env)
    first.close()
    second.close()
    assert calls == ["ensure", "lookup"]


def test_requalify_once_refuses_a_required_dependency_session(monkeypatch):
    from phase_loop_runtime import executable_dependency_startup as startup
    from phase_loop_runtime.executable_dependency import ExecutableDependencyError

    def refuse(_route):
        raise ExecutableDependencyError("dependency_route_unwired")

    monkeypatch.setattr(startup, "refuse_unwired_dependency_route", refuse)
    with pytest.raises(ExecutableDependencyError) as caught:
        q.requalify_once({})
    assert caught.value.code == "dependency_route_unwired"


def _client_hello(sni: bytes) -> bytes:
    extension = (b"\x00\x00" + (len(sni) + 5).to_bytes(2, "big")
                 + (len(sni) + 3).to_bytes(2, "big") + b"\x00"
                 + len(sni).to_bytes(2, "big") + sni)
    body = (b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x00\x02\x13\x01"
            + b"\x01\x00" + len(extension).to_bytes(2, "big") + extension)
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x03" + len(handshake).to_bytes(2, "big") + handshake


@contextmanager
def _front(tmp_path: Path, *, idle_ms=100):
    fake_socket = Path("/tmp") / (
        "pl-srt-" + sha256(str(tmp_path).encode()).hexdigest()[:16] + ".sock")
    fake_socket.unlink(missing_ok=True)
    module = tmp_path / "fake-srt.mjs"
    module.write_text("""
import { createServer } from 'node:net';
const socket = process.env.FAKE_SRT_SOCKET;
let server;
export const SandboxManager = {
  async initialize() {
    server = createServer(client => {
      let head = Buffer.alloc(0);
      client.on('data', chunk => {
        head = Buffer.concat([head, chunk]);
        if (head.includes('\\r\\n\\r\\n')) {
          client.write('HTTP/1.1 200 Connection Established\\r\\n\\r\\n');
          client.removeAllListeners('data');
        }
      });
    });
    await new Promise((resolve, reject) => {
      server.once('error', reject); server.listen(socket, resolve);
    });
  },
  getMitmCA() { return { secureContexts: new Map() }; },
  getLinuxHttpSocketPath() { return socket; },
  getProxyAuthToken() { return 'token'; },
  async reset() { await new Promise(resolve => server.close(resolve)); },
};
""")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "allow": [
            {"host": "daily-cloudcode-pa.googleapis.com", "port": 443,
             "method": "POST", "path_prefix": "/v1internal:"},
            {"host": "www.googleapis.com", "port": 443,
             "method": "GET", "path": "/oauth2/v2/userinfo"},
        ],
        "ca_cert": str(tmp_path / "ca.crt"), "ca_key": str(tmp_path / "ca.key"),
        "inner_sni_check": False, "front_idle_ms": idle_ms,
    }))
    proxy = seat_egress_proxy._data_path("proxy.mjs")
    process = subprocess.Popen(
        ["node", str(proxy), str(module), str(config)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "FAKE_SRT_SOCKET": str(fake_socket)},
    )
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 5)
    if not ready:
        process.kill()
        raise AssertionError(process.stderr.read() if process.stderr else "proxy did not start")
    line = process.stdout.readline()
    if not line:
        raise AssertionError(process.stderr.read() if process.stderr else "proxy exited")
    document = json.loads(line)
    try:
        yield process, Path(document["socket"])
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(5)
        fake_socket.unlink(missing_ok=True)


def _connect(front: Path, target=b"daily-cloudcode-pa.googleapis.com") -> socket.socket:
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(2)
    client.connect(str(front))
    auth = b"c3J0OnRva2Vu"  # base64("srt:token")
    client.sendall(b"CONNECT " + target + b":443 HTTP/1.1\r\nHost: " + target
                   + b":443\r\nProxy-Authorization: Basic " + auth + b"\r\n\r\n")
    assert b"200" in client.recv(256)
    return client


@pytest.mark.parametrize("malformation", ["extensions", "server-name-list"])
def test_front_refuses_lengths_that_exceed_their_enclosing_field(tmp_path, malformation):
    hello = bytearray(_client_hello(b"daily-cloudcode-pa.googleapis.com"))
    offset = 50 if malformation == "extensions" else 56
    value = int.from_bytes(hello[offset:offset + 2], "big") + 1
    hello[offset:offset + 2] = value.to_bytes(2, "big")
    with _front(tmp_path) as (_process, front):
        client = _connect(front)
        client.sendall(hello)
        assert client.recv(1) == b""
        client.close()


def test_front_refuses_non_clienthello_and_connect_sni_mismatch(tmp_path):
    with _front(tmp_path) as (_process, front):
        first = _connect(front)
        first.sendall(b"not a TLS ClientHello")
        assert first.recv(1) == b""
        first.close()
        second = _connect(front)
        second.sendall(_client_hello(b"www.googleapis.com"))
        assert second.recv(1) == b""
        second.close()


def test_front_idle_bound_is_pre_splice_only(tmp_path):
    with _front(tmp_path, idle_ms=50) as (_process, front):
        idle = socket.socket(socket.AF_UNIX)
        idle.settimeout(1)
        idle.connect(str(front))
        assert idle.recv(1) == b""
        idle.close()
        established = _connect(front)
        established.sendall(_client_hello(b"daily-cloudcode-pa.googleapis.com"))
        time.sleep(0.15)
        established.settimeout(0.05)
        with pytest.raises(TimeoutError):
            established.recv(1)
        established.close()


@pytest.mark.parametrize("idle_ms", [0, 30001, "30"])
def test_front_refuses_an_invalid_idle_bound_at_startup(tmp_path, idle_ms):
    module = tmp_path / "unused.mjs"
    module.write_text("export const SandboxManager = {};\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"allow": [], "front_idle_ms": idle_ms}))
    done = subprocess.run(
        ["node", str(seat_egress_proxy._data_path("proxy.mjs")), str(module), str(config)],
        capture_output=True, text=True, timeout=5,
    )
    assert done.returncode == 3
    assert "front idle bound is invalid" in done.stderr
