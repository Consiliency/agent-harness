from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import io
import json
from pathlib import Path
import socket
import subprocess
import urllib.parse

import pytest

from phase_loop_runtime import review_stage, seat_egress_proxy
from phase_loop_runtime.seat_route_contract import AllowlistRef


GEMINI_BYTES_SHA256 = "7ed38bb15aee22b55c1952c6b6edddf6b54fc7fe0420c300097990592a16348f"
GEMINI_CONTENT_SHA256 = "e29dc83b60705beed3d87c600b023dc959a51c76c5e1ab8df9001b1d7daaa296"


def test_gemini_allowlist_bytes_and_content_digest_are_frozen(tmp_path, monkeypatch):
    source = seat_egress_proxy._data_path("gemini-allowlist.json")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == GEMINI_BYTES_SHA256
    baseline = seat_egress_proxy.allowlist_ref("gemini")
    assert baseline.content_digest == GEMINI_CONTENT_SHA256
    assert len(baseline.probe_rows) == len(baseline.request_set) + 4
    assert [row["decision"] for row in baseline.probe_rows[:3]] == ["allow"] * 3
    assert [row["decision"] for row in baseline.probe_rows[3:]] == ["refuse"] * 4

    changed = json.loads(source.read_text(encoding="utf-8"))
    changed["measured_and_refused"] = [*changed["measured_and_refused"], "new.invalid"]
    fixture = tmp_path / "gemini-allowlist.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    real_data_path = seat_egress_proxy._data_path
    monkeypatch.setattr(
        seat_egress_proxy,
        "_data_path",
        lambda name: fixture if name == "gemini-allowlist.json" else real_data_path(name),
    )
    widened = seat_egress_proxy.allowlist_ref("gemini")
    assert widened.content_digest != baseline.content_digest
    assert widened.probe_rows != baseline.probe_rows


@pytest.mark.parametrize("port", [80, 444])
def test_provider_allowlists_are_tls_443_only(tmp_path, monkeypatch, port):
    document = json.loads(
        seat_egress_proxy._data_path("gemini-allowlist.json").read_text(encoding="utf-8")
    )
    document["leg"] = "fixture"
    document["allow"][0]["port"] = port
    fixture = tmp_path / "fixture-allowlist.json"
    fixture.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(seat_egress_proxy, "_data_path", lambda _name: fixture)
    _assert_code(
        seat_egress_proxy.INTEGRITY_CODE,
        lambda: seat_egress_proxy.allowlist_ref("fixture"),
    )


def test_public_proxy_api_cannot_disable_any_attestation():
    parameters = inspect.signature(seat_egress_proxy.start_proxy).parameters
    assert list(parameters) == ["allowlist_id", "refuse_all"]
    assert parameters["allowlist_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "inner_sni_check" not in parameters
    source = inspect.getsource(seat_egress_proxy.start_proxy)
    assert '"inner_sni_check": True' in source


def _assert_code(expected: str, call) -> seat_egress_proxy.EgressLayerUnavailable:
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        call()
    assert caught.value.code == expected
    return caught.value


def test_node_absence_execution_and_version_are_not_installed(monkeypatch):
    monkeypatch.setattr(
        review_stage, "trusted_host_executable", lambda _name: (_ for _ in ()).throw(ValueError()),
    )
    _assert_code(seat_egress_proxy.NOT_INSTALLED_CODE, seat_egress_proxy._node)

    monkeypatch.setattr(review_stage, "trusted_host_executable", lambda _name: "/trusted/node")
    monkeypatch.setattr(
        seat_egress_proxy.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError()),
    )
    _assert_code(seat_egress_proxy.NOT_INSTALLED_CODE, seat_egress_proxy._node)
    monkeypatch.setattr(
        seat_egress_proxy.subprocess,
        "run",
        lambda *a, **_k: subprocess.CompletedProcess(a, 0, "v1.0.0\n", ""),
    )
    _assert_code(seat_egress_proxy.NOT_INSTALLED_CODE, seat_egress_proxy._node)


def test_install_absence_and_present_malformed_install_are_split(tmp_path):
    _assert_code(
        seat_egress_proxy.NOT_INSTALLED_CODE,
        lambda: seat_egress_proxy.verify_install(tmp_path / "absent"),
    )
    modules = tmp_path / "present" / "node_modules"
    package = modules / "@anthropic-ai" / "sandbox-runtime"
    package.mkdir(parents=True)
    (package / "package.json").write_text("not-json", encoding="utf-8")
    (modules / ".package-lock.json").write_text("{}", encoding="utf-8")
    _assert_code(
        seat_egress_proxy.INTEGRITY_CODE,
        lambda: seat_egress_proxy.verify_install(tmp_path / "present"),
    )


def test_ca_integrity_and_generation_failure_are_split(tmp_path, monkeypatch):
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    unsafe.chmod(0o755)
    monkeypatch.setattr(seat_egress_proxy, "ca_dir", lambda: unsafe)
    _assert_code(
        seat_egress_proxy.INTEGRITY_CODE,
        lambda: seat_egress_proxy.ensure_ca(Path("/srt.js"), "/trusted/node"),
    )

    generated = tmp_path / "generated"
    monkeypatch.setattr(seat_egress_proxy, "ca_dir", lambda: generated)
    monkeypatch.setattr(
        seat_egress_proxy.subprocess,
        "run",
        lambda *a, **_k: subprocess.CompletedProcess(a, 1, "", "failed"),
    )
    _assert_code(
        seat_egress_proxy.START_FAILED_CODE,
        lambda: seat_egress_proxy.ensure_ca(Path("/srt.js"), "/trusted/node"),
    )


class _FakeProcess:
    _next_pid = 100

    def __init__(self) -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


def _proxy_inputs(monkeypatch, tmp_path):
    cert = tmp_path / "ca.crt"
    key = tmp_path / "ca.key"
    cert.write_text("certificate", encoding="ascii")
    key.write_text("key", encoding="ascii")
    monkeypatch.setattr(seat_egress_proxy, "_node", lambda: "/trusted/node")
    monkeypatch.setattr(seat_egress_proxy, "verify_install", lambda: Path("/srt.js"))
    monkeypatch.setattr(seat_egress_proxy, "ensure_ca", lambda _srt, _node: (cert, key))
    monkeypatch.setattr(seat_egress_proxy, "ca_fingerprint", lambda _cert: "a" * 64)


def test_process_spawn_and_readiness_failures_are_start_failed(tmp_path, monkeypatch):
    _proxy_inputs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        seat_egress_proxy.subprocess, "Popen", lambda *_a, **_k: (_ for _ in ()).throw(OSError()),
    )
    _assert_code(
        seat_egress_proxy.START_FAILED_CODE,
        lambda: seat_egress_proxy.start_proxy(allowlist_id="gemini").__enter__(),
    )

    process = _FakeProcess()
    monkeypatch.setattr(seat_egress_proxy, "_READY_TIMEOUT_S", 0.0)
    import select

    monkeypatch.setattr(select, "select", lambda *_a, **_k: ([], [], []))
    _assert_code(
        seat_egress_proxy.START_FAILED_CODE,
        lambda: seat_egress_proxy._read_ready(process),
    )
    process.stdout = io.StringIO("not-json\n")
    monkeypatch.setattr(select, "select", lambda *_a, **_k: ([process.stdout], [], []))
    _assert_code(
        seat_egress_proxy.START_FAILED_CODE,
        lambda: seat_egress_proxy._read_ready(process),
    )


@pytest.mark.parametrize("missing", ("tls_inspection", "inner_sni_check", "fail_closed_front"))
@pytest.mark.parametrize("value", (None, False))
def test_missing_or_false_ready_attestation_is_tls_unterminated(
    missing, value, tmp_path, monkeypatch,
):
    _proxy_inputs(monkeypatch, tmp_path)
    process = _FakeProcess()
    monkeypatch.setattr(seat_egress_proxy.subprocess, "Popen", lambda *_a, **_k: process)
    ready = {
        "socket": "/proxy.sock", "token": "token", "tls_inspection": True,
        "inner_sni_check": True, "fail_closed_front": True,
    }
    if value is None:
        ready.pop(missing)
    else:
        ready[missing] = value
    monkeypatch.setattr(seat_egress_proxy, "_read_ready", lambda _process: ready)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="gemini"):
            pass
    assert caught.value.code == seat_egress_proxy.TLS_UNTERMINATED_CODE


def test_each_start_gets_one_distinct_process_and_token(tmp_path, monkeypatch):
    _proxy_inputs(monkeypatch, tmp_path)
    processes = []

    def popen(*_a, **_k):
        process = _FakeProcess()
        process.token = f"token-{process.pid}"
        processes.append(process)
        return process

    monkeypatch.setattr(seat_egress_proxy.subprocess, "Popen", popen)
    monkeypatch.setattr(
        seat_egress_proxy,
        "_read_ready",
        lambda process: {
            "socket": f"/proxy-{process.pid}.sock", "token": process.token,
            "tls_inspection": True, "inner_sni_check": True, "fail_closed_front": True,
        },
    )
    with seat_egress_proxy.start_proxy(allowlist_id="gemini") as first:
        with seat_egress_proxy.start_proxy(allowlist_id="gemini") as second:
            assert first.process is not second.process
            assert first.proxy_url != second.proxy_url
            assert first.allowlist_id == second.allowlist_id == "gemini"
            assert first.allowlist_digest == second.allowlist_digest == GEMINI_CONTENT_SHA256
            first_evidence = seat_egress_proxy.egress_evidence(first)
            assert first_evidence["allowlist_id"] == "gemini"
            assert first_evidence["allowlist_digest"] == GEMINI_CONTENT_SHA256
    assert len(processes) == 2


def test_unavailable_code_uses_the_typed_exception_not_its_text(monkeypatch):
    monkeypatch.setattr(
        seat_egress_proxy,
        "_node",
        lambda: (_ for _ in ()).throw(
            seat_egress_proxy.EgressLayerUnavailable(
                seat_egress_proxy.INTEGRITY_CODE, "arbitrary changed wording",
            )
        ),
    )
    assert seat_egress_proxy.unavailable_code() == seat_egress_proxy.INTEGRITY_CODE


def test_every_unavailable_raise_site_sets_a_literal_typed_code():
    tree = ast.parse(Path(seat_egress_proxy.__file__).read_text(encoding="utf-8"))
    calls = [
        node.exc for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "EgressLayerUnavailable"
    ]
    allowed = {
        "NOT_INSTALLED_CODE", "INTEGRITY_CODE", "TLS_UNTERMINATED_CODE",
        "START_FAILED_CODE", "ALLOWLIST_MISSING_CODE",
    }
    assert calls
    assert all(
        len(call.args) >= 2 and isinstance(call.args[0], ast.Name) and call.args[0].id in allowed
        for call in calls
    )


def _fixture_ref(allowlist_id: str) -> AllowlistRef:
    return AllowlistRef(
        id=allowlist_id, content_digest=hashlib.sha256(allowlist_id.encode()).hexdigest(),
        request_set=({
            "host": f"{allowlist_id}.invalid", "port": 443, "method": "GET", "path": "/",
        },),
        probe_rows=(),
    )


def _connect_status(proxy, host: str) -> bytes:
    token = urllib.parse.urlsplit(proxy.proxy_url).password
    assert token
    authorization = base64.b64encode(f"srt:{token}".encode()).decode()
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(proxy.socket)
        client.sendall(
            f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
            f"Proxy-Authorization: Basic {authorization}\r\n\r\n".encode()
        )
        return client.recv(128)


def test_real_front_binds_each_process_to_its_own_allowlist(monkeypatch):
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        pytest.skip(f"the local seat egress layer is unavailable: {reason}")
    refs = {name: _fixture_ref(name) for name in ("fixture-a", "fixture-b")}
    monkeypatch.setattr(seat_egress_proxy, "allowlist_ref", lambda allowlist_id: refs[allowlist_id])
    with seat_egress_proxy.start_proxy(allowlist_id="fixture-a") as first, \
            seat_egress_proxy.start_proxy(allowlist_id="fixture-b") as second:
        assert first.process.pid != second.process.pid
        assert first.proxy_url != second.proxy_url
        assert (first.allowlist_id, second.allowlist_id) == ("fixture-a", "fixture-b")
        # Positive control: each process admits its own listed host, so a refusal below
        # is the allowlist binding, not a proxy that refuses everything.
        assert _connect_status(first, "fixture-a.invalid").startswith(b"HTTP/1.1 200")
        assert _connect_status(second, "fixture-b.invalid").startswith(b"HTTP/1.1 200")
        for proxy, host in ((first, "fixture-b.invalid"), (second, "fixture-a.invalid"),
                            (first, "not-listed.invalid"), (second, "not-listed.invalid")):
            assert _connect_status(proxy, host).startswith(b"HTTP/1.1 403")


def test_allowlist_id_cannot_escape_packaged_data():
    _assert_code(
        seat_egress_proxy.ALLOWLIST_MISSING_CODE,
        lambda: seat_egress_proxy.allowlist_ref("../gemini"),
    )
