"""Regression tests for Consiliency/agent-harness#2034:
Keep the seat egress proxy's exit status and a bounded, sanitized stderr tail in
``EgressLayerUnavailable`` when the proxy fails to start, while draining and discarding
stderr in steady state so a running proxy can never block on a full stderr pipe or grow
unbounded memory.
"""

from __future__ import annotations

import base64
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from phase_loop_runtime import seat_egress_proxy


def _stub_proxy_inputs(monkeypatch, tmp_path: Path, script_path: Path) -> None:
    cert = tmp_path / "ca.pem"
    key = tmp_path / "ca.key"
    cert.write_text("dummy-cert", encoding="utf-8")
    key.write_text("dummy-key", encoding="utf-8")
    srt = tmp_path / "srt-index.js"
    srt.write_text("", encoding="utf-8")

    orig_data_path = seat_egress_proxy._data_path
    monkeypatch.setattr(seat_egress_proxy, "_node", lambda: sys.executable)
    monkeypatch.setattr(seat_egress_proxy, "_require_srt_host_tools", lambda _node: None)
    monkeypatch.setattr(seat_egress_proxy, "verify_install", lambda: srt)
    monkeypatch.setattr(seat_egress_proxy, "ensure_ca", lambda _srt, _node: (cert, key))
    monkeypatch.setattr(
        seat_egress_proxy,
        "_data_path",
        lambda name: script_path if name == "proxy.mjs" else orig_data_path(name),
    )
    monkeypatch.setattr(seat_egress_proxy, "ca_fingerprint", lambda _cert: "0" * 64)


def test_start_failure_keeps_exit_code_and_bounded_stderr_tail(tmp_path, monkeypatch):
    failing = tmp_path / "fail_proxy.py"
    failing.write_text(
        "import sys\n"
        "sys.stderr.write('noise-' * 600 + '\\n')\n"
        "sys.stderr.write('fatal: address already in use on port 0\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, failing)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("failing proxy should not have started")

    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    detail = str(caught.value)
    assert "exit=3" in detail
    assert "fatal: address already in use on port 0" in detail
    assert "..." in detail
    assert len(detail) < 700


def test_start_failure_redacts_ready_token_from_stderr_tail(tmp_path, monkeypatch):
    bad_attest = tmp_path / "bad_attest_proxy.py"
    secret_token = "tok_super_secret_per_launch_value_999"
    bad_attest.write_text(
        "import json, sys\n"
        f"tok = {secret_token!r}\n"
        "sys.stderr.write(f'debug leak {tok}\\n')\n"
        "sys.stderr.flush()\n"
        "sys.stdout.write(json.dumps({'socket': '/tmp/x.sock', 'token': tok, 'tls_inspection': False}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, bad_attest)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("unattested proxy should not have started")

    assert caught.value.code == seat_egress_proxy.TLS_UNTERMINATED_CODE
    detail = str(caught.value)
    assert "exit=7" in detail
    assert "<redacted>" in detail
    assert secret_token not in detail
    assert not hasattr(caught.value, "_observed_secrets")


def test_start_failure_redacts_invalid_ready_token_basic_auth_pem_url_and_c1_controls(
    tmp_path, monkeypatch
):
    bad_ready = tmp_path / "bad_ready_proxy.py"
    secret_token = "tok_invalid_ready_secret_42"
    basic_b64 = base64.b64encode(f"srt:{secret_token}".encode("utf-8")).decode("ascii")
    other_b64 = base64.b64encode(b"srt:another_secret_value").decode("ascii")
    url_pass = "urlpass_super_secret_88"
    pem_body = "MIIE_SYNTHETIC_PRIVATE_KEY_PAYLOAD_LINE"
    bad_ready.write_text(
        "import json, sys\n"
        f"tok = {secret_token!r}\n"
        f"basic_b64 = {basic_b64!r}\n"
        f"other_b64 = {other_b64!r}\n"
        f"url_pass = {url_pass!r}\n"
        f"pem_body = {pem_body!r}\n"
        "pem_begin = '-----' + 'BEGIN PRIVATE KEY' + '-----'\n"
        "pem_end = '-----' + 'END PRIVATE KEY' + '-----'\n"
        "sys.stderr.write(\n"
        "    f'raw={tok} bare={basic_b64}\\n'\n"
        "    f'Proxy-Authorization: Basic {other_b64}\\n'\n"
        "    f'http://srt:{url_pass}@127.0.0.1:3128\\n'\n"
        "    f'{pem_begin}\\n{pem_body}\\n{pem_end}\\n'\n"
        "    'c1-ctrl:\\x85bad\\x9b31m-end\\n'\n"
        ")\n"
        "sys.stderr.flush()\n"
        # Invalid socket causes _read_ready() to reject the record before returning.
        "sys.stdout.write(json.dumps({'socket': '', 'token': tok}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(5)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, bad_ready)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("invalid ready record should have failed startup")

    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    detail = str(caught.value)
    assert "exit=5" in detail
    assert "<redacted>" in detail
    for forbidden in (secret_token, basic_b64, other_b64, url_pass, pem_body, "\x85", "\x9b"):
        assert forbidden not in detail
    assert not hasattr(caught.value, "_observed_secrets")


def test_steady_state_drains_large_stderr_without_blocking_and_does_not_wrap_body_errors(
    tmp_path, monkeypatch
):
    done_marker = tmp_path / "stderr-drained.ok"
    noisy = tmp_path / "noisy_proxy.py"
    noisy.write_text(
        "import json, pathlib, sys\n"
        f"marker = pathlib.Path({str(done_marker)!r})\n"
        "sys.stdout.write(json.dumps({\n"
        "    'socket': '/tmp/ready.sock',\n"
        "    'token': 'tok_ready',\n"
        "    'tls_inspection': True,\n"
        "    'inner_sni_check': True,\n"
        "    'fail_closed_front': True,\n"
        "}) + '\\n')\n"
        "sys.stdout.flush()\n"
        # Write well over typical pipe buffers (512 KiB) and acknowledge completion only
        # after every write returns, so a disabled drainer would stall before writing marker.
        "chunk = 'x' * 4096 + '\\n'\n"
        "for _ in range(128):\n"
        "    sys.stderr.write(chunk)\n"
        "sys.stderr.flush()\n"
        "marker.write_text('drained', encoding='utf-8')\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, noisy)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
            assert proxy.socket == "/tmp/ready.sock"
            deadline = time.monotonic() + 5.0
            while not done_marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert done_marker.exists(), "proxy stalled writing stderr while context was open"
            raise seat_egress_proxy.EgressLayerUnavailable("custom_body_code", "caller raised")

    assert caught.value.code == "custom_body_code"
    assert str(caught.value) == "caller raised"


def test_start_timeout_keeps_partial_stderr_and_terminates_hung_proxy(tmp_path, monkeypatch):
    hung = tmp_path / "hung_proxy.py"
    hung.write_text(
        "import sys, time\n"
        "sys.stderr.write('stuck waiting for loopback bind\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, hung)
    monkeypatch.setattr(seat_egress_proxy, "_READY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(seat_egress_proxy, "_START_EXIT_SETTLE_S", 0.05)
    monkeypatch.setattr(seat_egress_proxy, "_SHUTDOWN_TIMEOUT_S", 0.1)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("hung proxy should not have started")

    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    assert "stuck waiting for loopback bind" in str(caught.value)


def test_teardown_does_not_block_when_descendant_holds_stderr_open(tmp_path, monkeypatch):
    pid_file = tmp_path / "descendant.pid"
    holder = tmp_path / "holder_proxy.py"
    holder.write_text(
        "import pathlib, subprocess, sys\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(10)'],\n"
        "    stdin=subprocess.DEVNULL,\n"
        "    stdout=subprocess.DEVNULL,\n"
        ")\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n"
        "sys.stderr.write('proxy exited while descendant kept stderr open\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(4)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, holder)
    monkeypatch.setattr(seat_egress_proxy, "_START_STDERR_DRAIN_WAIT_S", 0.1)
    monkeypatch.setattr(seat_egress_proxy, "_SHUTDOWN_TIMEOUT_S", 0.2)

    started_at = time.monotonic()
    try:
        with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
            with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
                pytest.fail("failing proxy should not have started")
        elapsed = time.monotonic() - started_at
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8").strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    assert elapsed < 2.0, f"teardown blocked waiting on descendant stderr ({elapsed:.2f}s)"
    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    detail = str(caught.value)
    assert "exit=4" in detail
    assert "proxy exited while descendant kept stderr open" in detail


def test_drainer_start_failure_still_cleans_up_child_and_stdio(tmp_path, monkeypatch):
    sleeper = tmp_path / "sleeper_proxy.py"
    sleeper.write_text("import sys, time\ntime.sleep(30)\n", encoding="utf-8")
    _stub_proxy_inputs(monkeypatch, tmp_path, sleeper)
    monkeypatch.setattr(seat_egress_proxy, "_SHUTDOWN_TIMEOUT_S", 0.1)

    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def tracking_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(seat_egress_proxy.subprocess, "Popen", tracking_popen)
    monkeypatch.setattr(
        seat_egress_proxy,
        "_StderrTail",
        lambda _pipe: (_ for _ in ()).throw(RuntimeError("injected thread start failure")),
    )

    with pytest.raises(RuntimeError, match="injected thread start failure"):
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("proxy should not yield when drainer fails to start")

    assert len(spawned) == 1
    proc = spawned[0]
    assert proc.poll() is not None
    assert proc.stdin is not None and proc.stdin.closed
    assert proc.stdout is not None and proc.stdout.closed
    assert proc.stderr is not None and proc.stderr.closed


def test_start_failure_with_surrogate_ready_token_preserves_typed_refusal(tmp_path, monkeypatch):
    bad_surrogate = tmp_path / "surrogate_ready_proxy.py"
    bad_surrogate.write_text(
        "import sys\n"
        "sys.stderr.write('startup failed after malformed ready token\\n')\n"
        "sys.stderr.flush()\n"
        # JSON with an escaped lone surrogate (\ud800) and empty socket.
        "sys.stdout.write('{\"socket\": \"\", \"token\": \"\\\\ud800bad\"}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(6)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, bad_surrogate)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("malformed ready record should have failed startup")

    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    detail = str(caught.value)
    assert "exit=6" in detail
    assert "startup failed after malformed ready token" in detail
    assert not hasattr(caught.value, "_observed_secrets")


@pytest.mark.parametrize("terminated", [True, False])
def test_start_failure_oversized_pem_block_never_leaks_key_body_across_eviction(
    tmp_path, monkeypatch, terminated
):
    pem_proxy = tmp_path / f"pem_proxy_{terminated}.py"
    tail_marker = "SYNTHETIC_PEM_KEY_TAIL_PAYLOAD_9999"
    body_lines = "MIIE_KEY_CHUNK_LINE_" * 3 + "\n"
    # Exceed the 8 KiB capture window so a naive ring buffer would evict the PEM header.
    script = (
        "import sys\n"
        "pem_begin = '-----' + 'BEGIN PRIVATE KEY' + '-----'\n"
        "pem_end = '-----' + 'END PRIVATE KEY' + '-----'\n"
        "sys.stderr.write(pem_begin + '\\n')\n"
        f"for _ in range(250): sys.stderr.write({body_lines!r})\n"
        f"sys.stderr.write({tail_marker + chr(10)!r})\n"
    )
    if terminated:
        script += (
            "sys.stderr.write(pem_end + '\\n')\n"
            "sys.stderr.write('fatal: bind failed after key dump\\n')\n"
        )
    script += "sys.stderr.flush()\nsys.exit(8)\n"
    pem_proxy.write_text(script, encoding="utf-8")
    _stub_proxy_inputs(monkeypatch, tmp_path, pem_proxy)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("failing proxy should not have started")

    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    detail = str(caught.value)
    assert "exit=8" in detail
    assert "<redacted>" in detail
    assert tail_marker not in detail
    assert "MIIE_KEY_CHUNK_LINE_" not in detail
    if terminated:
        assert "fatal: bind failed after key dump" in detail


def test_start_failure_oversized_bearer_line_never_leaks_secret_tail(tmp_path, monkeypatch):
    bearer_proxy = tmp_path / "bearer_proxy.py"
    tail_secret = "BEARER_TAIL_SECRET_MARKER_7777"
    bearer_proxy.write_text(
        "import sys\n"
        "sys.stderr.write('prefix line\\n')\n"
        "sys.stderr.write('Authorization: Bearer ' + 'A' * 12000 + "
        f"{tail_secret!r} + '\\n')\n"
        "sys.stderr.write('fatal: upstream rejected handshake\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(9)\n",
        encoding="utf-8",
    )
    _stub_proxy_inputs(monkeypatch, tmp_path, bearer_proxy)

    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pytest.fail("failing proxy should not have started")

    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    detail = str(caught.value)
    assert "exit=9" in detail
    assert "<redacted>" in detail
    assert tail_secret not in detail
    assert "AAAA" not in detail
    assert "fatal: upstream rejected handshake" in detail


def test_split_tab_indented_line_at_cap_boundary_matches_single_read():
    class _ChunkedPipe:
        def __init__(self, chunks: list[str]) -> None:
            self._chunks = list(chunks)

        def read(self, _size: int = -1) -> str:
            return self._chunks.pop(0) if self._chunks else ""

        def close(self) -> None:
            return None

    prior = ("x" * 80 + "\n") * 101 + "y" * 8 + "\n"
    assert len(prior) == 8190
    single = seat_egress_proxy._StderrTail(
        _ChunkedPipe([prior + "\tlisten failed: EADDRINUSE\n"])
    )
    split = seat_egress_proxy._StderrTail(
        _ChunkedPipe([prior + "\tlisten failed: ", "EADDRINUSE\n"])
    )
    try:
        single_tail = single.tail(wait_s=2.0)
        split_tail = split.tail(wait_s=2.0)
    finally:
        single.close(timeout=1.0)
        split.close(timeout=1.0)

    assert "listen failed: EADDRINUSE" in single_tail
    assert "listen failed: EADDRINUSE" in split_tail
    assert split_tail == single_tail
