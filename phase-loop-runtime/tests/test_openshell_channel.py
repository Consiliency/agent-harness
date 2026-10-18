"""Synthetic loopback TLS only; no real issuer, enrollment or Rust authority."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, replace
import json
import subprocess
from pathlib import Path
import sys

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
        ], check=True, capture_output=True, timeout=10)
        result.append((key.read_bytes(), cert.read_bytes()))
    return result


@pytest.fixture
def config(certificates, monkeypatch):
    monkeypatch.setattr(oc.placement_lease, "owner_id", lambda: "owner")
    return oc.ChannelConfig("https://localhost:443", "dedicated", "owner",
                            certificates[0][1], "synthetic-token", 1024, 0.5)


class ServerState:
    def __init__(self, process):
        self.process = process

    async def command(self, **command):
        async with asyncio.timeout(10):
            self.process.stdin.write(json.dumps(command).encode() + b"\n")
            await self.process.stdin.drain()
            line = await self.process.stdout.readline()
            assert line, f"TLS fixture exited: {self.process.returncode}"
            return json.loads(line)


@asynccontextmanager
async def tls_server(sdk, certificates, config, *, plaintext=False):
    # A separate interpreter keeps aio server shutdown out of the client's
    # Python credential-plugin/GIL lifecycle (r38). Pass the loaded SDK paths.
    paths = [str(Path(module.__file__).resolve().parent)
             for module in (sdk.proto, sdk.service)]
    paths.append(str(Path(sdk.grpc.__file__).resolve().parent.parent))
    helper = Path(__file__).with_name("_openshell_channel_server.py")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-B", "-c",
        "import runpy,sys; sys.path[:0] = " + repr(paths)
        + "; runpy.run_path(sys.argv[1], run_name='__main__')", str(helper),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    state = ServerState(process)
    try:
        ready = await state.command(key=certificates[0][0].decode(),
                                    cert=certificates[0][1].decode(), plaintext=plaintext)
        yield replace(config, endpoint=f"https://localhost:{ready['port']}"), state
    finally:
        process.stdin.close()  # EOF requests stop, including setup/assertion failures.
        try:
            await asyncio.wait_for(process.wait(), 10)
        finally:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), 5)
        assert process.returncode == 0, f"TLS fixture exited: {process.returncode}"


def request(sdk, *, stream=False, **kwargs):
    cls = sdk.proto.ExecCancellationLeaseRequest if stream else sdk.proto.ControlCancellationLeaseRequest
    return cls(owner_id="owner", workspace_scope={"workspace": "dedicated"}, **kwargs)


def test_server_reaped_after_body_failure(config, sdk, certificates):
    async def run():
        with pytest.raises(RuntimeError, match="body failure"):
            async with tls_server(sdk, certificates, config) as (_, state):
                raise RuntimeError("body failure")
        assert state.process.returncode == 0
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["startup", "shutdown", "exit"])
def test_server_failure_is_reported_and_reaped(config, sdk, certificates, monkeypatch, failure):
    spawn = asyncio.create_subprocess_exec
    children = []

    async def faulty_server(*args, **kwargs):
        code = "import asyncio,sys; sys.stdin.readline(); "
        if failure == "exit":
            code += "sys.exit(7)"
        else:
            if failure == "shutdown":
                code += "print('{\"port\": 1}', flush=True); "
            code += "asyncio.run(asyncio.Event().wait())"
        child = await spawn(sys.executable, "-I", "-B", "-c", code, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", faulty_server)

    async def run():
        with pytest.raises(AssertionError if failure == "exit" else TimeoutError):
            async with tls_server(sdk, certificates, config):
                assert failure == "shutdown"
        assert len(children) == 1
        assert children[0].returncode == (7 if failure == "exit" else -9)
    asyncio.run(run())


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
            assert (await state.command())["calls"] == 1
        assert len(calls) == 1
    asyncio.run(run())
    with pytest.raises(TypeError):
        oc.authenticated_channel(config, sdk.service, options=[("grpc.enable_retries", 1)])


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", ["UNAVAILABLE", "ABORTED", "DEADLINE_EXCEEDED", "UNAUTHENTICATED", "PERMISSION_DENIED"])
def test_authenticated_rpc_never_retries(config, sdk, certificates, stream, status):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            await state.command(failure=status)
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    if stream:
                        await stub.ExecCancellationLease(request(sdk, stream=True), timeout=1).read()
                    else:
                        await stub.ControlCancellationLease(request(sdk), timeout=1)
                assert error.value.code().name == (await state.command())["failure"]
                assert (await state.command())["calls"] == 1
    asyncio.run(run())


def test_receive_limit_enforced(config, sdk, certificates):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            await state.command(size=cfg.receive_limit_bytes + 1)
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    await stub.ExecCancellationLease(request(sdk, stream=True), timeout=1).read()
                assert error.value.code() == sdk.grpc.StatusCode.RESOURCE_EXHAUSTED
                assert (await state.command())["calls"] == 1
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
            await state.command(failure="UNAVAILABLE")
            async with oc.authenticated_channel(cfg, sdk.service) as stub:
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    if stream:
                        await stub.ExecCancellationLease(request(sdk, stream=True), timeout=1).read()
                    else:
                        await stub.ControlCancellationLease(request(sdk), timeout=1)
                assert error.value.code().name == (await state.command())["failure"]
                assert (await state.command())["calls"] == 1
    asyncio.run(run())


def test_tls_ready_does_not_authorize_bearer(config, sdk, certificates):
    async def run():
        async with tls_server(sdk, certificates, config) as (cfg, state):
            async with oc.authenticated_channel(replace(cfg, bearer_token="rejected"), sdk.service) as stub:
                assert (await state.command())["calls"] == 0
                with pytest.raises(sdk.grpc.aio.AioRpcError) as error:
                    await stub.ControlCancellationLease(request(sdk), timeout=1)
                assert error.value.code() == sdk.grpc.StatusCode.UNAUTHENTICATED
                assert (await state.command())["calls"] == 1
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
            assert (await state.command())["calls"] == 0
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
                assert (await state.command())["calls"] == 0
                await state.command(hold=True)
                call = stub.ControlCancellationLease(request(sdk), timeout=10)
                await state.command(wait="entered")
            assert call.cancelled()
            await state.command(wait="stopped")
            with pytest.raises(oc.TransportError, match="context"):
                stub.ControlCancellationLease(request(sdk), timeout=1)
    asyncio.run(run())
