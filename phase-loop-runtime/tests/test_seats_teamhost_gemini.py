"""TEAMHOST Gemini admission-key and fail-closed-front proofs (agent-harness#1820)."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import io
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from phase_loop_runtime import agy_provenance as prov
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker
from phase_loop_runtime import seat_egress_proxy
from phase_loop_runtime import seat_jail


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


def _client_hello(sni: bytes, *, record_minor: int = 0x03) -> bytes:
    extension = (b"\x00\x00" + (len(sni) + 5).to_bytes(2, "big")
                 + (len(sni) + 3).to_bytes(2, "big") + b"\x00"
                 + len(sni).to_bytes(2, "big") + sni)
    body = (b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x00\x02\x13\x01"
            + b"\x01\x00" + len(extension).to_bytes(2, "big") + extension)
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return bytes((0x16, 0x03, record_minor)) + len(handshake).to_bytes(2, "big") + handshake


@contextmanager
def _front(tmp_path: Path, *, idle_ms=100, probe_inner_host=False):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable on the clean test PATH")
    fake_socket = Path("/tmp") / (
        "pl-srt-" + sha256(str(tmp_path).encode()).hexdigest()[:16] + ".sock")
    fake_socket.unlink(missing_ok=True)
    module = tmp_path / "fake-srt.mjs"
    module.write_text("""
import { createServer } from 'node:net';
const socket = process.env.FAKE_SRT_SOCKET;
let server;
export const SandboxManager = {
  async initialize(options) {
    if (process.env.PROBE_INNER_HOST === '1') {
      const verdict = await options.network.filterRequest(new Request(
        'https://daily-cloudcode-pa.googleapis.com/v1internal:test',
        { method: 'POST', headers: { host: 'storage.googleapis.com' } }));
      if (!verdict || verdict.action !== 'deny') throw new Error('inner Host was admitted');
    }
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
        [node, str(proxy), str(module), str(config)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "FAKE_SRT_SOCKET": str(fake_socket),
             "PROBE_INNER_HOST": "1" if probe_inner_host else "0"},
    )
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 5)
    if not ready:
        process.kill()
        raise AssertionError(process.stderr.read() if process.stderr else "proxy did not start")
    deadline = time.monotonic() + 5
    document = None
    while document is None:
        line = process.stdout.readline()
        if not line:
            raise AssertionError(process.stderr.read() if process.stderr else "proxy exited")
        candidate = json.loads(line)
        if "socket" in candidate:
            document = candidate
        assert time.monotonic() < deadline
    try:
        yield process, Path(document["socket"])
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(5)
        fake_socket.unlink(missing_ok=True)


def _connect(front: Path, target=b"daily-cloudcode-pa.googleapis.com",
             auth=b"c3J0OnRva2Vu") -> socket.socket:
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(2)
    client.connect(str(front))
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


def test_front_refuses_shape_b_nonstandard_record_with_an_allowed_sni(tmp_path):
    with _front(tmp_path) as (_process, front):
        client = _connect(front)
        client.sendall(_client_hello(
            b"daily-cloudcode-pa.googleapis.com", record_minor=0x04))
        assert client.recv(1) == b""
        client.close()


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
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable on the clean test PATH")
    module = tmp_path / "unused.mjs"
    module.write_text("export const SandboxManager = {};\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"allow": [], "front_idle_ms": idle_ms}))
    done = subprocess.run(
        [node, str(seat_egress_proxy._data_path("proxy.mjs")), str(module), str(config)],
        capture_output=True, text=True, timeout=5,
    )
    assert done.returncode == 3
    assert "front idle bound is invalid" in done.stderr


def test_inner_host_mismatch_is_behaviorally_refused(tmp_path):
    with _front(tmp_path, probe_inner_host=True) as (process, _front_socket):
        assert process.poll() is None


def test_front_buffers_nothing_after_the_splice(tmp_path, monkeypatch):
    needle = "    buf = Buffer.concat([buf, chunk]);\n"
    text = Path(seat_egress_proxy._data_path("proxy.mjs")).read_text(encoding="utf-8")
    assert text.count(needle) == 1
    copy = tmp_path / "proxy.mjs"
    copy.write_text(text.replace(
        needle, needle + "    process.stderr.write(`buffered=${buf.length}\\n`);\n"),
        encoding="utf-8")
    monkeypatch.setattr(seat_egress_proxy, "_data_path", lambda _name: copy)
    with _front(tmp_path) as (process, front):
        client = _connect(front)
        client.sendall(_client_hello(b"daily-cloudcode-pa.googleapis.com"))
        time.sleep(0.1)
        client.sendall(b"x" * 65536)
        time.sleep(0.1)
        client.close()
    assert process.stderr is not None
    lengths = [int(line.split("=")[1]) for line in process.stderr.read().splitlines()
               if line.startswith("buffered=")]
    assert lengths and max(lengths) <= 16389


def test_rendered_environment_names_are_the_contract_names():
    rendered = gh.GeminiHeartbeatProfile(panel_invoker._broker_subscription_env({
        name: "x" for name in (
            "HOME", "LANG", "LC_ALL", "LC_CTYPE", "NO_COLOR", "PATH", "TERM",
            "SECRET", "XDG_CONFIG_HOME", "TMPDIR")
    })).env
    assert tuple(sorted(rendered)) == q._operation("completion").env_names


def test_profile_digest_follows_the_owned_settings(monkeypatch):
    original = q.agy_profile_digest()
    monkeypatch.setattr(panel_invoker, "_broker_agy_settings_bytes", lambda: b"{}\n")
    assert q.agy_profile_digest() != original


@pytest.mark.parametrize("operation", ["completion", "cancel", "owner-loss"])
def test_validate_records_rejects_a_changed_pass_predicate_for_each_operation(
        monkeypatch, operation):
    class PredicateWasAccepted(RuntimeError):
        pass

    class SourceSentinel:
        def __eq__(self, _other):
            raise PredicateWasAccepted

    record = {"schema": "gemini_heartbeat_qualification.v1", "operation": operation,
              "source_sha256": SourceSentinel()}
    with pytest.raises(PredicateWasAccepted):
        q.validate_records(
            record, expected_source_sha256={}, expected_image_sha256="a" * 64,
            expected_help_sha256="b" * 64, expected_profile_sha256="c" * 64)
    contract = tuple(
        item._replace(pass_predicate_id="changed_predicate")
        if item.operation_id == operation else item
        for item in q.OPERATIONS_CONTRACT)
    monkeypatch.setattr(q, "OPERATIONS_CONTRACT", contract)
    with pytest.raises(q.QualificationFailure, match="record rejected"):
        q.validate_records(
            record, expected_source_sha256={}, expected_image_sha256="a" * 64,
            expected_help_sha256="b" * 64, expected_profile_sha256="c" * 64)


def _lkg_fixture(tmp_path, monkeypatch):
    subject = _subject(tmp_path, "agy-new", b"#!/bin/sh\necho new\n")
    lkg_bytes = b"#!/bin/sh\necho last-known-good\n"
    store = _seed(lkg_bytes)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: True)
    monkeypatch.setattr(q, "_run_help", lambda *_: HELP)
    q.register_last_known_good(
        lambda: gh.VerifiedImage.from_bytes(lkg_bytes, tmp_path / "agy-lkg"))
    return subject, lkg_bytes, store


def test_the_review_seat_route_uses_the_last_known_good_image(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    subject, lkg_bytes, _store = _lkg_fixture(tmp_path, monkeypatch)
    image = agy_integrity.admit_for_seat(subject, {"PATH": str(tmp_path)})
    try:
        assert image.sha256 == sha256(lkg_bytes).hexdigest()
    finally:
        image.close()


def test_last_known_good_needs_a_subject_with_no_record(tmp_path, monkeypatch):
    subject, _lkg, store = _lkg_fixture(tmp_path, monkeypatch)
    asset = SimpleNamespace(name=HOST.asset, version="9.9.9", digest="sha256:" + "0" * 64)
    digest = sha256(subject.read_bytes()).hexdigest()
    store.put_provenance(
        SimpleNamespace(image_sha256=digest, platform=HOST.name, asset=asset),
        q.agy_profile_digest())
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        gh.admit({"PATH": str(tmp_path)}, subject_path=subject)


def test_lookup_only_verdict_agrees_with_the_seat_admission_code(tmp_path, monkeypatch):
    image = b"#!/bin/sh\necho held\n"
    path = _subject(tmp_path, "agy", image)
    env = {"PATH": str(tmp_path)}
    _seed(image)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: False)
    expected = q.AgyVerdict("refuses", "agy_image_unqualified", "self_qualification_disabled")
    assert q.admission_verdict({}, path, execute=False) == expected
    assert q.admission_verdict(env, path, execute=True) == expected


def test_lookup_only_verdict_mirrors_a_seat_without_pidfd_support(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    image = b"#!/bin/sh\necho release\n"
    path = _subject(tmp_path, "agy", image)
    env = {"PATH": str(tmp_path)}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {sha256(image).hexdigest(): "e" * 64})
    monkeypatch.delattr(os, "pidfd_open")
    agy_integrity.admit_for_seat(path, env).close()
    assert q.admission_verdict({}, path, execute=False).status == "admits"
    assert q.admission_verdict(env, path, execute=True).status == "admits"


def test_lookup_only_verdict_refuses_when_the_image_cannot_be_sealed(tmp_path, monkeypatch):
    image = b"#!/bin/sh\necho release\n"
    path = _subject(tmp_path, "agy", image)
    env = {"PATH": str(tmp_path)}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {sha256(image).hexdigest(): "e" * 64})

    def unsealed(_data, _path=None):
        raise ValueError(gh._CAPABILITY)

    def unsealed_stream(_fd, *, path=None):
        raise ValueError(gh._CAPABILITY)

    monkeypatch.setattr(gh.VerifiedImage, "from_bytes", unsealed)
    # The seat path streams the image into its memfd (AGYFRESH §1.2).
    monkeypatch.setattr(gh.VerifiedImage, "from_fd", unsealed_stream)
    expected = q.AgyVerdict("refuses", "agy_image_unqualified", "admission_error")
    assert q.admission_verdict({}, path, execute=False) == expected
    assert q.admission_verdict(env, path, execute=True) == expected


def test_lookup_only_verdict_counts_the_last_known_good_image(tmp_path, monkeypatch):
    subject, _lkg, _store = _lkg_fixture(tmp_path, monkeypatch)
    assert q.admission_verdict({}, subject, execute=False) == q.AgyVerdict(
        "unknown", None, "launch_measurement")


def test_a_cancelled_preflight_leaves_the_requalification_available(tmp_path, monkeypatch):
    _subject(tmp_path, "agy", b"#!/bin/sh\necho c\n")
    env = {"PATH": str(tmp_path)}
    outcomes = iter([ValueError(q.CANCELLED), None])
    calls = []

    def ensure(*_a, **_k):
        calls.append("ensure")
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return "admission"

    monkeypatch.setattr(q, "ensure_admitted", ensure)
    with pytest.raises(ValueError, match=q.CANCELLED):
        q.requalify_once(env)
    assert q.requalify_once(env) == "admission"
    assert calls == ["ensure", "ensure"]


def test_requalification_threads_the_resolved_subject_path(tmp_path, monkeypatch):
    subject = _subject(tmp_path, "agy-native", b"#!/bin/sh\necho native\n")
    seen = []
    monkeypatch.setattr(
        q, "ensure_admitted",
        lambda *_a, **kw: seen.append(("ensure", kw["subject_path"])) or "first")
    monkeypatch.setattr(
        gh, "admit",
        lambda *_a, **kw: seen.append(("lookup", kw["subject_path"])) or "second")
    assert q.requalify_once({}, subject_path=subject) == "first"
    assert q.requalify_once({}, subject_path=subject) == "second"
    assert seen == [("ensure", subject), ("lookup", subject)]


def test_first_use_admits_the_threaded_subject_not_the_path_hit(tmp_path, monkeypatch):
    _subject(tmp_path, "agy", b"#!/bin/sh\necho frontdoor\n")
    native_bytes = b"#!/bin/sh\necho native\n"
    native = _subject(tmp_path, "agy-native", native_bytes)
    digest = sha256(native_bytes).hexdigest()
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {digest: "e" * 64})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: False)
    admission = q.ensure_admitted({"PATH": str(tmp_path)}, subject_path=native)
    try:
        assert admission.image.sha256 == digest
    finally:
        admission.close()


class _FakeProxyProcess:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


@pytest.mark.parametrize("failed", ["node", "tools", "install", "ca"])
def test_start_proxy_checks_every_startup_integrity_gate_before_spawn(monkeypatch, failed):
    def stop(name):
        if failed == name:
            raise seat_egress_proxy.EgressLayerUnavailable(name, name)

    monkeypatch.setattr(seat_egress_proxy, "_node", lambda: stop("node") or "/usr/bin/node")
    monkeypatch.setattr(seat_egress_proxy, "_require_srt_host_tools", lambda _node: stop("tools"))
    monkeypatch.setattr(
        seat_egress_proxy, "verify_install", lambda: stop("install") or Path("/srt.mjs"))
    monkeypatch.setattr(
        seat_egress_proxy, "ensure_ca",
        lambda *_a: stop("ca") or (Path("/ca.crt"), Path("/ca.key")))
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_a, **_kw: pytest.fail("proxy spawned past failed gate"))
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable, match=failed):
        with seat_egress_proxy.start_proxy(allowlist_id="gemini"):
            pass


@pytest.mark.parametrize("ready", [
    {"socket": "/front", "token": "t", "tls_inspection": False,
     "inner_sni_check": True, "fail_closed_front": True},
    {"socket": "/front", "token": "t", "tls_inspection": True,
     "inner_sni_check": False, "fail_closed_front": True},
    {"socket": "/front", "token": "t", "tls_inspection": True,
     "inner_sni_check": True, "fail_closed_front": False},
])
def test_start_proxy_refuses_each_missing_runtime_integrity_fact(tmp_path, monkeypatch, ready):
    cert = tmp_path / "ca.crt"
    key = tmp_path / "ca.key"
    cert.write_text("unused")
    key.write_text("unused")
    process = _FakeProxyProcess()
    monkeypatch.setattr(seat_egress_proxy, "_node", lambda: "/usr/bin/node")
    monkeypatch.setattr(seat_egress_proxy, "_require_srt_host_tools", lambda _node: None)
    monkeypatch.setattr(seat_egress_proxy, "verify_install", lambda: Path("/srt.mjs"))
    monkeypatch.setattr(seat_egress_proxy, "ensure_ca", lambda *_a: (cert, key))
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_kw: process)
    monkeypatch.setattr(seat_egress_proxy, "_read_ready", lambda _process: ready)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as refused:
        with seat_egress_proxy.start_proxy(allowlist_id="gemini"):
            pass
    assert refused.value.code == seat_egress_proxy.TLS_UNTERMINATED_CODE


def test_gemini_jail_view_contains_no_ca_key_bytes(tmp_path):
    review = tmp_path / "seat"
    tree = tmp_path / "reviewed" / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    review.mkdir()
    config = review / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
    panel_invoker._write_gemini_config(config, b'{"token": {}}')
    ca_dir = tmp_path / "seat-egress-ca"
    ca_dir.mkdir()
    cert = ca_dir / "ca.crt"
    key = ca_dir / "ca.key"
    cert.write_bytes(b"synthetic certificate\n")
    key_bytes = b"TEAMHOST-SYNTHETIC-CA-PRIVATE-KEY-BYTES"
    key.write_bytes(key_bytes)
    jail = seat_jail.build_seat_jail(
        "gemini", review, Path("/usr/bin/true"), tree=tree,
        bundle_memfd=seat_jail.memfd_with("b", b"B"),
        instructions_memfd=seat_jail.memfd_with("i", b"I"), seat_ids=(3, 3),
        gemini_config=config, egress_ca=cert, egress_proxy="http://127.0.0.1:3128")
    try:
        for kind, source, _target in (
                (jail.process_owner[index:index + 3])
                for index, value in enumerate(jail.process_owner)
                if value in ("--bind", "--ro-bind")):
            assert kind in ("--bind", "--ro-bind")
            path = Path(source)
            assert not (path.is_dir() and key.is_relative_to(path))
            # The generated sentinel exists only in this synthetic per-launch view. Scan
            # every bound file in that view; the ancestor check above also makes a mutant
            # that binds the CA directory fail before its key can enter the seat.
            visible = [path] if path.is_file() else (
                [candidate for candidate in path.rglob("*") if candidate.is_file()]
                if path.is_dir() and path.is_relative_to(tmp_path) else [])
            for candidate in visible:
                assert key_bytes not in candidate.read_bytes()
    finally:
        seat_jail.close_jail_fds(jail)


def test_shape_b_nonstandard_record_is_refused_by_the_installed_front():
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
    with seat_egress_proxy.start_proxy(allowlist_id="gemini") as proxy:
        parsed = urlsplit(proxy.proxy_url)
        auth = __import__("base64").b64encode(
            f"{parsed.username}:{parsed.password}".encode("utf-8"))
        client = _connect(Path(proxy.socket), auth=auth)
        client.sendall(_client_hello(
            b"daily-cloudcode-pa.googleapis.com", record_minor=0x04))
        assert client.recv(1) == b""
        client.close()


def _receipt_runner_module():
    path = (Path(__file__).resolve().parents[2] / "plans/evidence/seat-jail-1132"
            / "run_mutation_receipts_1170.py")
    if not path.is_file():
        pytest.skip("the receipt runner is a repo-only file")
    spec = importlib.util.spec_from_file_location("teamhost_receipt_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mutation_receipt_document_uses_the_exact_run_base(monkeypatch):
    runner = _receipt_runner_module()
    exact = "a" * 40
    monkeypatch.setattr(
        runner.subprocess, "run",
        lambda *_a, **_kw: SimpleNamespace(stdout=exact + "\n"))
    assert runner._run_base() == exact
    document = runner._document([], runner._run_base())
    assert document["base"] == exact
    assert "attribution_note" not in document


def test_unattributed_mutation_receipt_cites_the_issue_and_invents_no_head(monkeypatch):
    runner = _receipt_runner_module()
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(stdout=""))
    assert runner._run_base() == "unattributed"
    document = runner._document([], runner._run_base())
    assert document["base"] == "unattributed"
    assert "agent-harness#1555" in document["attribution_note"]
    assert not any(
        isinstance(value, str) and len(value) in (40, 64)
        and all(char in "0123456789abcdef" for char in value)
        for value in document.values())


# ---------------------------------------------------------------------------
# agent-harness#2053: closed refusal reasons on agy_image_unqualified verdicts
# ---------------------------------------------------------------------------

def test_verdict_refusal_reasons_cover_doctor_and_execute_branches(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    image = b"#!/bin/sh\necho candidate\n"
    path = _subject(tmp_path, "agy", image)
    env = {"PATH": str(tmp_path)}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: True)

    seen_reasons: set[str] = set()

    def _assert_both(target, expected_reason: str, *, check_seat: bool = True):
        doctor = q.admission_verdict(env, target, execute=False)
        executed = q.admission_verdict(env, target, execute=True)
        expected = q.AgyVerdict("refuses", "agy_image_unqualified", expected_reason)
        assert doctor == expected
        assert executed == expected
        assert doctor.reason in q.VERDICT_REFUSAL_REASONS
        assert str(tmp_path) not in doctor.reason
        if check_seat:
            with pytest.raises(agy_integrity.AgyImageUnqualified) as info:
                agy_integrity.admit_for_seat(Path(target), env)
            assert info.value.args == ("agy_image_unqualified",)
            assert str(info.value) == "agy_image_unqualified"
            assert info.value.reason == expected_reason
        seen_reasons.add(expected_reason)

    # 1. no_qualification_record (absent store on fresh host)
    _assert_both(path, "no_qualification_record")

    # 2. no_qualification_record (ok store, no records for this image)
    store = q.Store()
    store.create()
    _assert_both(path, "no_qualification_record")

    # 3. self_qualification_disabled
    with monkeypatch.context() as ctx:
        ctx.setattr(q, "self_qualification_enabled", lambda: False)
        _assert_both(path, "self_qualification_disabled")

    # 4. qualification_failed (recorded failed entry)
    store.put_failed(
        sha256(image).hexdigest(),
        sha256(HELP).hexdigest(),
        HOST,
        q.agy_profile_digest(),
        "completion",
        "canary_failed",
    )
    _assert_both(path, "qualification_failed")
    store.remove(("failed",))

    # 5. host_unknown (_host raises ValueError on both ok and absent stores)
    with monkeypatch.context() as ctx:
        ctx.setattr(prov, "detect_platform",
                    lambda **_: (_ for _ in ()).throw(prov.ProvenanceError("unknown arch")))
        _assert_both(path, "host_unknown")
        ctx.setenv("XDG_STATE_HOME", str(tmp_path / "absent-state"))
        _assert_both(path, "host_unknown")

    # 6. store_unsafe (world-writable store directory)
    store.host_dir.chmod(0o777)
    try:
        _assert_both(path, "store_unsafe")
    finally:
        store.host_dir.chmod(0o700)

    # 7. image_unreadable (missing path, non-regular directory, over-bound size)
    _assert_both(tmp_path / "missing-agy", "image_unreadable")
    _assert_both(tmp_path, "image_unreadable")
    with monkeypatch.context() as ctx:
        ctx.setattr(prov, "MAX_MEMBER_BYTES", 4)
        _assert_both(path, "image_unreadable")

    # 8. admission_error (memfd seal failure, unexpected admit_seat error, untagged refusal)
    with monkeypatch.context() as ctx:
        def _seal_err(*_a, **_kw):
            raise gh.AgyCanaryEvidenceError("seal_failed")

        ctx.setattr(gh.VerifiedImage, "from_bytes", _seal_err)
        ctx.setattr(gh.VerifiedImage, "from_fd", _seal_err)
        _assert_both(path, "admission_error")

    with monkeypatch.context() as ctx:
        ctx.setattr(
            q, "admit_seat",
            lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("unexpected fault")),
        )
        with pytest.raises(agy_integrity.AgyImageUnqualified) as info:
            agy_integrity.admit_for_seat(path, env)
        assert info.value.reason == "admission_error"
        assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    with monkeypatch.context() as ctx:
        ctx.setattr(
            agy_integrity, "admit_for_seat",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                agy_integrity.AgyImageUnqualified("agy_image_unqualified")
            ),
        )
        assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    assert seen_reasons == set(q.VERDICT_REFUSAL_REASONS)


def test_agy_integrity_check_release_only_reports_closed_reasons(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    image = b"#!/bin/sh\necho unqualified\n"
    path = _subject(tmp_path, "agy", image)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})

    with pytest.raises(agy_integrity.AgyImageUnqualified) as info:
        agy_integrity.check(path)
    assert str(info.value) == "agy_image_unqualified"
    assert info.value.reason == "no_qualification_record"

    with pytest.raises(agy_integrity.AgyImageUnqualified) as info:
        agy_integrity.check(tmp_path / "missing-agy")
    assert info.value.reason == "image_unreadable"

    with monkeypatch.context() as ctx:
        ctx.setattr(
            gh.VerifiedImage, "from_fd",
            lambda *_a, **_kw: (_ for _ in ()).throw(gh.AgyCanaryEvidenceError("seal_failed")),
        )
        with pytest.raises(agy_integrity.AgyImageUnqualified) as info:
            agy_integrity.check(path)
        assert info.value.reason == "admission_error"


def test_agy_qualification_status_cli_and_doctor_schema_accept_refusal_reasons(
    tmp_path, monkeypatch, capsys
):
    from importlib.resources import files
    import jsonschema
    from phase_loop_runtime import seat_subject

    image = b"#!/bin/sh\necho candidate\n"
    path = _subject(tmp_path, "agy", image)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: True)
    monkeypatch.setattr(q, "hold_status", lambda *_a, **_kw: {"enabled": False})
    monkeypatch.setattr(
        panel_invoker, "_broker_subscription_env", lambda: {"PATH": str(tmp_path)}
    )
    monkeypatch.setattr(
        seat_subject,
        "resolve_seat_subject",
        lambda leg, _env: seat_subject.SeatSubject(leg, "standalone", path, None, None),
    )

    assert q.cli_main(SimpleNamespace(action="status")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == {
        "code": "agy_image_unqualified",
        "reason": "no_qualification_record",
        "status": "refuses",
    }

    store = q.Store()
    store.create()
    store.host_dir.chmod(0o777)
    try:
        assert q.cli_main(SimpleNamespace(action="status")) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == {
            "code": "agy_image_unqualified",
            "reason": "store_unsafe",
            "status": "refuses",
        }
    finally:
        store.host_dir.chmod(0o700)

    package = files("phase_loop_runtime") / "schemas"
    schema = json.loads((package / "phase-loop-doctor.v1.schema.json").read_text())
    golden = json.loads((package / "phase-loop-doctor.v1.golden.json").read_text())
    for reason in q.VERDICT_REFUSAL_REASONS:
        candidate = dict(golden)
        candidate["seat_cli_qualification"] = [
            {
                "leg": "gemini",
                "status": "refuses",
                "code": "agy_image_unqualified",
                "reason": reason,
            }
        ]
        jsonschema.validate(candidate, schema)


def test_verdict_refusal_reasons_hardening_r2(tmp_path, monkeypatch):
    """Regression coverage for config/store/help/host/capability/LKG/constructor edge cases."""
    import errno
    from phase_loop_runtime import agy_hold, agy_integrity

    image = b"#!/bin/sh\necho candidate\n"
    path = _subject(tmp_path, "agy", image)
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    cfg_root = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_root))
    cfg_file = cfg_root / "agent-harness" / "advisor-boards.toml"
    cfg_file.parent.mkdir(parents=True, exist_ok=True)

    # P1 (config): malformed advisor-boards.toml -> admission_error (not self_qualification_disabled)
    cfg_file.write_text("[agy\nbroken = true\n", encoding="utf-8")
    assert q.admission_verdict(env, path, execute=False) == q.AgyVerdict(
        "refuses", "agy_image_unqualified", "admission_error"
    )
    assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
        "refuses", "agy_image_unqualified", "admission_error"
    )

    # Explicit opt-out -> self_qualification_disabled
    cfg_file.write_text("[agy]\nself_qualification = false\n", encoding="utf-8")
    assert q.admission_verdict(env, path, execute=False) == q.AgyVerdict(
        "refuses", "agy_image_unqualified", "self_qualification_disabled"
    )
    assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
        "refuses", "agy_image_unqualified", "self_qualification_disabled"
    )

    # P2 (hold config): malformed [agy].hold -> admission_error in both modes
    cfg_file.write_text('[agy]\nself_qualification = true\nhold = "yes"\n', encoding="utf-8")
    assert q.admission_verdict(env, path, execute=False) == q.AgyVerdict(
        "refuses", "agy_image_unqualified", "admission_error"
    )
    assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
        "refuses", "agy_image_unqualified", "admission_error"
    )
    cfg_file.unlink()

    # P1 (store): bad-mode provenance entry (status == ok) and missing key with populated store
    store = _seed(image)
    prov_files = list(store.host_dir.glob("provenance-*.json"))
    assert len(prov_files) == 1
    prov_files[0].chmod(0o644)
    try:
        assert store.status() == "ok"
        assert q.admission_verdict(env, path, execute=False) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "store_unsafe"
        )
        assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "store_unsafe"
        )
    finally:
        prov_files[0].chmod(0o600)

    # Bad-mode qualified entry -> execute mode reports store_unsafe
    qual_files = list(store.host_dir.glob("qualified-*.json"))
    assert len(qual_files) == 1
    qual_files[0].chmod(0o644)
    try:
        with monkeypatch.context() as ctx:
            ctx.setattr(q, "measure_help", lambda *_a, **_kw: HELP)
            assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
                "refuses", "agy_image_unqualified", "store_unsafe"
            )
    finally:
        qual_files[0].chmod(0o600)

    # Missing key with provenance still present (status == absent) -> store_unsafe in both modes
    key_path = store.host_dir / "key"
    saved_key = key_path.read_bytes()
    key_path.unlink()
    try:
        assert store.status() == "absent"
        assert q.admission_verdict(env, path, execute=False) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "store_unsafe"
        )
        assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "store_unsafe"
        )
    finally:
        key_path.write_bytes(saved_key)
        key_path.chmod(0o600)

    # P1 (help measurement local EIO via owned_profile -> ValueError(_CAPABILITY)):
    # must report admission_error (not self_qualification_disabled) while preserving hold routing
    cred = tmp_path / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    cred.parent.mkdir(parents=True, exist_ok=True)
    cred.write_text("token", encoding="utf-8")
    real_sealed_tree_fd = gh._sealed_tree_fd

    def _fail_settings_memfd(*, data, executable, label):
        if label == "agy-settings":
            raise OSError(errno.EIO, "synthetic EIO on agy-settings")
        return real_sealed_tree_fd(data=data, executable=executable, label=label)

    hold_reasons_seen: list[str] = []
    with monkeypatch.context() as ctx:
        q._HELP_MEMO.clear()
        ctx.setattr(gh, "_sealed_tree_fd", _fail_settings_memfd)
        ctx.setattr(
            q, "admit_held",
            lambda _env, *, reason, **_kw: hold_reasons_seen.append(reason) or None,
        )
        assert q.admission_verdict(env, path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )
    assert hold_reasons_seen == ["self_qualification_disabled"]

    # P2 (host transient failure): lookup _host() raises once then succeeds -> still host_unknown;
    # and lookup succeeds then _hold_or_refuse succeeds -> admit_held IS reached (no extra _host() call)
    unqualified_path = _subject(tmp_path, "agy-unqualified", b"#!/bin/sh\necho other\n")
    with monkeypatch.context() as ctx:
        calls = iter([ValueError("transient host fail"), HOST])

        def _flaky_host():
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item

        ctx.setattr(q, "_host", _flaky_host)
        ctx.setattr(agy_hold, "hold_enabled", lambda: False)
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "host_unknown"
        )

    with monkeypatch.context() as ctx:
        host_calls = []
        held_reached = []

        def _counted_host():
            host_calls.append(1)
            if len(host_calls) <= 3:
                return HOST
            raise ValueError("unexpected extra host call")

        ctx.setattr(q, "_host", _counted_host)
        ctx.setattr(
            q, "admit_held",
            lambda _env, **_kw: held_reached.append(True) or None,
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "no_qualification_record"
        )
        assert held_reached == [True]
        assert len(host_calls) == 3

    with monkeypatch.context() as ctx:
        host_calls = []
        held_reached = []

        def _hold_host_fail():
            host_calls.append(1)
            if len(host_calls) <= 2:
                return HOST
            raise ValueError("transient host failure at hold check")

        ctx.setattr(q, "_host", _hold_host_fail)
        ctx.setattr(
            q, "admit_held",
            lambda _env, **_kw: held_reached.append(True) or None,
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "host_unknown"
        )
        assert held_reached == []

    # P2 (pidfd / local capability failure): both doctor and execute report admission_error
    with monkeypatch.context() as ctx:
        ctx.setattr(
            gh, "_local_capabilities",
            lambda: (_ for _ in ()).throw(ValueError(gh._CAPABILITY)),
        )
        assert q.admission_verdict(env, unqualified_path, execute=False) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    # P2 (LKG help EIO and LKG provider OSError)
    with monkeypatch.context() as ctx:
        lkg_bytes = image
        ctx.setattr(
            q, "_LAST_KNOWN_GOOD_PROVIDER",
            lambda: gh.VerifiedImage.from_bytes(lkg_bytes, path),
        )
        ctx.setattr(
            q, "measure_help",
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError(errno.EIO, "lkg help EIO")),
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    with monkeypatch.context() as ctx:
        ctx.setattr(
            q, "_LAST_KNOWN_GOOD_PROVIDER",
            lambda: (_ for _ in ()).throw(OSError(errno.EIO, "lkg provider EIO")),
        )
        assert q.admission_verdict(env, unqualified_path, execute=False) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    # P3 (AgyImageUnqualified preserves RuntimeError constructor contract)
    empty = agy_integrity.AgyImageUnqualified()
    assert empty.args == ()
    assert str(empty) == ""
    assert empty.reason is None
    multi = agy_integrity.AgyImageUnqualified("a", "b", reason="store_unsafe")
    assert multi.args == ("a", "b")
    assert multi.reason == "store_unsafe"


def test_verdict_refusal_reasons_hardening_r3(tmp_path, monkeypatch):
    """Regression coverage for r2 review findings (quiescence, LKG, hold faults, pidfd, closed LKG)."""
    import errno
    from phase_loop_runtime import agy_hold
    from phase_loop_runtime.advisor_board import config as board_config

    lkg_bytes = b"#!/bin/sh\necho lkg\n"
    lkg_path = _subject(tmp_path, "agy-lkg", lkg_bytes)
    unqualified_path = _subject(tmp_path, "agy-unqualified", b"#!/bin/sh\necho other\n")
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(agy_hold, "_WALK_ROOT", tmp_path)
    monkeypatch.setattr(agy_hold, "VENDOR_STORES", ())
    store = _seed(lkg_bytes)

    # P1 (quiescence propagation): ProviderProcessGroupQuiescenceError during LKG help
    # must propagate without calling the hold.
    with monkeypatch.context() as ctx:
        hold_called = []
        ctx.setattr(
            q, "_LAST_KNOWN_GOOD_PROVIDER",
            lambda: gh.VerifiedImage.from_bytes(lkg_bytes, lkg_path),
        )
        ctx.setattr(
            q, "measure_help",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                panel_invoker.ProviderProcessGroupQuiescenceError("quiescence_timeout")
            ),
        )
        ctx.setattr(
            q, "admit_held",
            lambda *_a, **_kw: hold_called.append(True) or None,
        )
        verdict = q.admission_verdict(env, unqualified_path, execute=True)
        assert verdict.status == "refuses"
        assert verdict.code != "agy_image_unqualified"
        assert hold_called == []

    # P1 (invalid failed entry must not block an otherwise qualified LKG image)
    store.put_failed(
        sha256(lkg_bytes).hexdigest(),
        sha256(HELP).hexdigest(),
        HOST,
        q.agy_profile_digest(),
        "completion",
        "old_failure",
    )
    failed_files = list(store.host_dir.glob("failed-*.json"))
    assert len(failed_files) == 1
    failed_files[0].chmod(0o644)
    try:
        with monkeypatch.context() as ctx:
            ctx.setattr(agy_hold, "hold_enabled", lambda: False)
            ctx.setattr(
                q, "_LAST_KNOWN_GOOD_PROVIDER",
                lambda: gh.VerifiedImage.from_bytes(lkg_bytes, lkg_path),
            )
            ctx.setattr(q, "measure_help", lambda *_a, **_kw: HELP)
            assert q.admission_verdict(env, unqualified_path, execute=False) == q.AgyVerdict(
                "unknown", None, "launch_measurement"
            )
            assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
                "admits", None, None
            )
    finally:
        failed_files[0].chmod(0o600)
        store.remove(("failed",))

    # P1 (hold candidate help EIO -> admission_error, not no_qualification_record)
    held_img = gh.VerifiedImage.from_bytes(lkg_bytes, lkg_path)
    try:
        agy_hold.retain(held_img, store, cache_version=lambda _d, _v: (9, 9, 9))
    finally:
        held_img.close()
    with monkeypatch.context() as ctx:
        ctx.setattr(q, "measure_help", lambda *_a, **_kw: HELP)
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "admits", None, None
        )
    with monkeypatch.context() as ctx:
        ctx.setattr(
            q, "measure_help",
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError(errno.EIO, "hold help EIO")),
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    # P1 (transient single-read hold config EIO -> admission_error on first read)
    with monkeypatch.context() as ctx:
        reads = iter([OSError(errno.EIO, "transient hold config EIO"), True])

        def _flaky_load_agy_hold(*, path=None):
            item = next(reads)
            if isinstance(item, Exception):
                raise item
            return item

        ctx.setattr(board_config, "load_agy_hold", _flaky_load_agy_hold)
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    # P2 (doctor mode preserves admits on release-qualified subject even if pidfd probe fails)
    release_bytes = b"#!/bin/sh\necho release\n"
    release_path = _subject(tmp_path, "agy-release", release_bytes)
    with monkeypatch.context() as ctx:
        ctx.setattr(gh, "QUALIFIED_IMAGES", {sha256(release_bytes).hexdigest(): "e" * 64})
        ctx.setattr(
            gh, "_local_capabilities",
            lambda: (_ for _ in ()).throw(ValueError(gh._CAPABILITY)),
        )
        assert q.admission_verdict(env, release_path, execute=False) == q.AgyVerdict(
            "admits", None, None
        )

    # P2 (closed VerifiedImage from LKG provider -> admission_error in both modes)
    def _closed_lkg():
        closed = gh.VerifiedImage.from_bytes(lkg_bytes, lkg_path)
        closed.close()
        return closed

    with monkeypatch.context() as ctx:
        ctx.setattr(agy_hold, "hold_enabled", lambda: False)
        ctx.setattr(q, "_LAST_KNOWN_GOOD_PROVIDER", _closed_lkg)
        assert q.admission_verdict(env, unqualified_path, execute=False) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )


def test_verdict_refusal_reasons_hardening_r4(tmp_path, monkeypatch):
    """Regression coverage for r3 review findings (LKG provider propagation, hold open/seal, host/opt-out agreement)."""
    import errno
    from phase_loop_runtime import agy_hold

    lkg_bytes = b"#!/bin/sh\necho lkg\n"
    lkg_path = _subject(tmp_path, "agy-lkg", lkg_bytes)
    unqualified_path = _subject(tmp_path, "agy-unqualified", b"#!/bin/sh\necho other\n")
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(agy_hold, "_WALK_ROOT", tmp_path)
    monkeypatch.setattr(agy_hold, "VENDOR_STORES", ())
    store = _seed(lkg_bytes)
    held_img = gh.VerifiedImage.from_bytes(lkg_bytes, lkg_path)
    try:
        agy_hold.retain(held_img, store, cache_version=lambda _d, _v: (9, 9, 9))
    finally:
        held_img.close()

    # Baseline: healthy hold admits
    with monkeypatch.context() as ctx:
        ctx.setattr(q, "measure_help", lambda *_a, **_kw: HELP)
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "admits", None, None
        )

    # P1: LKG provider raising OSError(EIO) or ProviderProcessGroupQuiescenceError must NOT
    # be swallowed into a hold admission.
    with monkeypatch.context() as ctx:
        ctx.setattr(q, "measure_help", lambda *_a, **_kw: HELP)
        ctx.setattr(
            q, "_LAST_KNOWN_GOOD_PROVIDER",
            lambda: (_ for _ in ()).throw(OSError(errno.EIO, "lkg provider EIO")),
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    with monkeypatch.context() as ctx:
        ctx.setattr(q, "measure_help", lambda *_a, **_kw: HELP)
        ctx.setattr(
            q, "_LAST_KNOWN_GOOD_PROVIDER",
            lambda: (_ for _ in ()).throw(
                panel_invoker.ProviderProcessGroupQuiescenceError("quiescence_timeout")
            ),
        )
        verdict = q.admission_verdict(env, unqualified_path, execute=True)
        assert verdict.status == "refuses"
        assert verdict.code != "agy_image_unqualified"

    # P1: Hold candidate open EIO and seal failure must report admission_error (not no_qualification_record)
    with monkeypatch.context() as ctx:
        ctx.setattr(
            agy_hold, "_open_candidate",
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError(errno.EIO, "candidate open EIO")),
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    real_from_fd = gh.VerifiedImage.from_fd
    calls = {"n": 0}

    def _fail_second_seal(fd, *, path=None):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise gh.AgyCanaryEvidenceError("candidate_seal_failed")
        return real_from_fd(fd, path=path)

    with monkeypatch.context() as ctx:
        ctx.setattr(gh.VerifiedImage, "from_fd", _fail_second_seal)
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "admission_error"
        )

    # P2: Explicit self_qualification=false + hold enabled + _host() failing -> host_unknown in BOTH modes
    cfg_file = tmp_path / "cfg" / "agent-harness" / "advisor-boards.toml"
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text("[agy]\nself_qualification = false\nhold = true\n", encoding="utf-8")
    with monkeypatch.context() as ctx:
        ctx.setattr(
            q, "_host",
            lambda: (_ for _ in ()).throw(ValueError("unknown host")),
        )
        assert q.admission_verdict(env, unqualified_path, execute=False) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "host_unknown"
        )
        assert q.admission_verdict(env, unqualified_path, execute=True) == q.AgyVerdict(
            "refuses", "agy_image_unqualified", "host_unknown"
        )
