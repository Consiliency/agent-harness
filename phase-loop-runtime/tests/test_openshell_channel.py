"""Synthetic loopback TLS only; no real issuer, enrollment or Rust authority."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, replace
import json
import subprocess
from types import SimpleNamespace

import pytest

from phase_loop_runtime import openshell_channel as oc
from test_openshell_transport_grpc import sdk as sdk


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    directory = tmp_path_factory.mktemp("channel-certs")
    result = []
    for name in ("trusted", "other"):
        key, cert = directory / f"{name}.key", directory / f"{name}.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
        ], check=True, capture_output=True)
        result.append((key.read_bytes(), cert.read_bytes()))
    return result


@pytest.fixture
def config(certificates, monkeypatch):
    monkeypatch.setattr(oc.placement_lease, "owner_id", lambda: "owner")
    return oc.ChannelConfig("https://localhost:443", "dedicated", "owner",
                            certificates[0][1], "synthetic-token", 1024, 0.5)


@asynccontextmanager
async def tls_server(sdk, certificates, config, *, plaintext=False):
    grpc, p = sdk.grpc, sdk.proto
    state = SimpleNamespace(calls=[], failure=None, size=0, hold=False,
                            entered=asyncio.Event(), stopped=asyncio.Event())

    async def receive(request, context):
        state.calls.append(request)
        metadata = dict(context.invocation_metadata())
        if metadata.get("authorization") != "Bearer synthetic-token":
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "refused")
        if state.failure:
            await context.abort(state.failure, "refused")
        if state.hold:
            state.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                state.stopped.set()

    class Service(sdk.service.OpenShellServicer):
        async def ControlCancellationLease(self, request, context):
            await receive(request, context)
            return p.ControlCancellationLeaseResponse()

        async def ExecCancellationLease(self, request, context):
            await receive(request, context)
            yield p.ExecSandboxEvent(stdout={"data": b"x" * state.size})

    server = grpc.aio.server()
    sdk.service.add_OpenShellServicer_to_server(Service(), server)
    if plaintext:
        port = server.add_insecure_port("127.0.0.1:0")
    else:
        port = server.add_secure_port("127.0.0.1:0", grpc.ssl_server_credentials([certificates[0]]))
    assert port
    await server.start()
    try:
        yield replace(config, endpoint=f"https://localhost:{port}"), state
    finally:
        await server.stop(None)


def request(sdk, *, stream=False, **kwargs):
    cls = sdk.proto.ExecCancellationLeaseRequest if stream else sdk.proto.ControlCancellationLeaseRequest
    return cls(owner_id="owner", workspace_scope={"workspace": "dedicated"}, **kwargs)


@pytest.mark.parametrize("endpoint", [
    "http://localhost:443", "unix:/tmp/socket", "dns:///localhost", "https://",
    "https://user:pass@localhost", "https://localhost/path", "https://localhost?",
    "https://localhost#", "https://localhost:0", "https://localhost:65536",
    "https://localhost:", "https://localhost:bad", "https://local host",
    "https://localhost\n", "https://local\\host", "https://a..b", "https://-host",
    "https://[::1%lo]:443", "https://[bad]", "https://host%2fpath", None,
    "https://[::1]suffix", "https://localhost:00443",
])
def test_invalid_endpoint(config, endpoint):
    with pytest.raises(oc.TransportError, match="invalid_channel_endpoint"):
        replace(config, endpoint=endpoint).validate()


@pytest.mark.parametrize("field,value,code", [
    ("ca_pem", b"", "trust"), ("ca_pem", b"bad", "trust"),
    ("ca_pem", None, "trust"), ("bearer_token", "", "credential"),
    ("bearer_token", "token\r\ninject", "credential"),
    ("receive_limit_bytes", -1, "receive_limit"), ("receive_limit_bytes", True, "receive_limit"),
    ("receive_limit_bytes", 2**31, "receive_limit"),
    ("connect_timeout_s", float("inf"), "timeout"), ("connect_timeout_s", 0, "timeout"),
    ("connect_timeout_s", float("nan"), "timeout"), ("connect_timeout_s", True, "timeout"),
    ("connect_timeout_s", 10**400, "timeout"),
    ("workspace", "", "scope"), ("owner_id", "other", "owner_workspace_refused"),
])
def test_invalid_config(config, field, value, code):
    with pytest.raises(oc.TransportError, match=code):
        replace(config, **{field: value}).validate()


def test_config_immutable_and_secrets_not_repr(config):
    with pytest.raises(FrozenInstanceError):
        config.receive_limit_bytes = -1
    assert config.bearer_token not in repr(config)
    assert "CERTIFICATE" not in repr(config)
    assert replace(config, endpoint="https://[::1]:123").target() == "[::1]:123"


def test_fixed_options_and_no_override(config, sdk, certificates, monkeypatch):
    original = sdk.grpc.aio.secure_channel
    calls = []

    def capture(target, credentials, **kwargs):
        calls.append(kwargs)
        assert kwargs == {"options": (
            ("grpc.enable_retries", 0), ("grpc.service_config_disable_resolution", 1),
            ("grpc.max_receive_message_length", config.receive_limit_bytes), ("grpc.enable_http_proxy", 0),
        )}
        return original(target, credentials, **kwargs)

    monkeypatch.setattr(sdk.grpc.aio, "secure_channel", capture)

    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                await stub.ControlCancellationLease(request(sdk), timeout=1)
            assert len(state.calls) == 1
        assert len(calls) == 1
    asyncio.run(run())
    with pytest.raises(TypeError):
        oc.authenticated_channel(config, sdk.service, options=[("grpc.enable_retries", 1)])


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", ["UNAVAILABLE", "ABORTED", "DEADLINE_EXCEEDED", "UNAUTHENTICATED", "PERMISSION_DENIED"])
def test_authenticated_rpc_never_retries(config, sdk, certificates, stream, status):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            state.failure = getattr(sdk.grpc.StatusCode, status)
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    if stream:
                        await stub.ExecCancellationLease(request(sdk, stream=True), timeout=1).read()
                    else:
                        await stub.ControlCancellationLease(request(sdk), timeout=1)
                assert error.value.code() == state.failure
                assert len(state.calls) == 1
    asyncio.run(run())


def test_receive_limit_enforced(config, sdk, certificates):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            state.size = cfg.receive_limit_bytes + 1
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    await stub.ExecCancellationLease(request(sdk, stream=True), timeout=1).read()
                assert error.value.code() == sdk.grpc.StatusCode.RESOURCE_EXHAUSTED
                assert len(state.calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("stream", [False, True])
def test_retry_policy_cannot_enable_retries(config, sdk, certificates, monkeypatch, stream):
    original = sdk.grpc.aio.secure_channel
    policy = json.dumps({"methodConfig": [{
        "name": [{"service": "openshell.v1.OpenShell"}],
        "retryPolicy": {"maxAttempts": 3, "initialBackoff": "0.01s",
                        "maxBackoff": "0.01s", "backoffMultiplier": 1,
                        "retryableStatusCodes": ["UNAVAILABLE"]},
    }]})

    def inject_policy(target, credentials, *, options):
        return original(target, credentials, options=(*options, ("grpc.service_config", policy)))

    monkeypatch.setattr(sdk.grpc.aio, "secure_channel", inject_policy)

    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            state.failure = sdk.grpc.StatusCode.UNAVAILABLE
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    if stream:
                        await stub.ExecCancellationLease(request(sdk, stream=True), timeout=1).read()
                    else:
                        await stub.ControlCancellationLease(request(sdk), timeout=1)
                assert error.value.code() == state.failure
                assert len(state.calls) == 1
    asyncio.run(run())


def test_tls_ready_does_not_authorize_bearer(config, sdk, certificates):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            async with oc.authenticated_channel(replace(cfg, bearer_token="rejected"), sdk.service) as stub:
                assert state.calls == []
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    await stub.ControlCancellationLease(request(sdk), timeout=1)
                assert error.value.code() == sdk.grpc.StatusCode.UNAUTHENTICATED
                assert len(state.calls) == 1
    asyncio.run(run())


def test_connection_cancellation_closes_channel(config, sdk, monkeypatch):
    async def run():
        entered = asyncio.Event()
        closed = []

        class Channel:
            async def channel_ready(self):
                entered.set()
                await asyncio.Event().wait()

            async def close(self, grace):
                closed.append(grace)

        monkeypatch.setattr(sdk.grpc.aio, "secure_channel", lambda *args, **kwargs: Channel())

        async def connect():
            async with oc.authenticated_channel(config, sdk.service):
                pytest.fail("cancelled connection yielded a stub")

        task = asyncio.create_task(connect())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [None]
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["roots", "hostname", "plaintext"])
def test_tls_fails_closed(config, sdk, certificates, failure):
    async def run():
        async with tls_server(sdk, certificates, config, plaintext=failure == "plaintext") as (cfg, state):
            if failure == "roots":
                cfg = replace(cfg, ca_pem=certificates[1][1])
            if failure == "hostname":
                cfg = replace(cfg, endpoint=cfg.endpoint.replace("localhost", "127.0.0.1"))
            with pytest.raises(oc.TransportError, match="channel_connect_timeout"):
                async with oc.authenticated_channel(cfg, sdk.service):
                    pytest.fail("untrusted connection accepted")
            assert state.calls == []
    asyncio.run(run())


def test_scope_lifetime_and_cancel(config, sdk, certificates, monkeypatch):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                wrong = request(sdk)
                wrong.owner_id = "other"
                with pytest.raises(oc.TransportError, match="owner_workspace_refused"):
                    stub.ControlCancellationLease(wrong, timeout=1)
                wrong.owner_id = "owner"
                wrong.workspace_scope.workspace = "other"
                with pytest.raises(oc.TransportError, match="owner_workspace_refused"):
                    stub.ControlCancellationLease(wrong, timeout=1)
                with pytest.raises(oc.TransportError, match="timeout"):
                    stub.ControlCancellationLease(request(sdk), timeout=None)
                with monkeypatch.context() as patch:
                    patch.setattr(oc.os, "getpid", lambda: -1)
                    with pytest.raises(oc.TransportError, match="context"):
                        stub.ControlCancellationLease(request(sdk), timeout=1)
                with monkeypatch.context() as patch:
                    patch.setattr(oc.placement_lease, "owner_id", lambda: "new-owner")
                    with pytest.raises(oc.TransportError, match="owner_workspace_refused"):
                        stub.ControlCancellationLease(request(sdk), timeout=1)

                def other_loop():
                    async def call():
                        with pytest.raises(oc.TransportError, match="context"):
                            stub.ControlCancellationLease(request(sdk), timeout=1)
                    asyncio.run(call())
                await asyncio.to_thread(other_loop)
                assert state.calls == []
                state.hold = True
                call = stub.ControlCancellationLease(request(sdk), timeout=10)
                await asyncio.wait_for(state.entered.wait(), 1)
            assert call.cancelled()
            await asyncio.wait_for(state.stopped.wait(), 1)
            with pytest.raises(oc.TransportError, match="context"):
                stub.ControlCancellationLease(request(sdk), timeout=1)
    asyncio.run(run())
