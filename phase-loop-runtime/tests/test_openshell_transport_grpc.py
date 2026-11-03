"""Stock exec stream tests using loopback mTLS only."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from phase_loop_runtime import openshell_transport as ot
import test_openshell_transport as model

# Stock v0.1.4 fixtures are checked in; no private SDK environment is needed.
from _openshell_channel_server import stock_bindings, mtls_config, mtls_material as mtls_material
from phase_loop_runtime.openshell_channel import stock_exec_channel
from uuid import UUID, uuid4


@asynccontextmanager
async def stock_server(material, *, mode='normal', options=()):
    grpc = pytest.importorskip('grpc')
    p = stock_bindings()
    state = SimpleNamespace(calls=[], deadlines=[], entered=asyncio.Event(), stopped=asyncio.Event())
    async def execute(request, context):
        state.calls.append(request)
        state.deadlines.append(context.time_remaining())
        state.entered.set()
        try:
            if mode == 'silence': await asyncio.Event().wait()
            if mode == 'drop': await context.abort(grpc.StatusCode.UNAVAILABLE, 'SECRET details')
            yield p.ExecSandboxEvent(stdout={'data': b'out'})
            if mode == 'drop-after-output':
                await context.abort(grpc.StatusCode.UNAVAILABLE, 'SECRET partial stream')
            if mode == 'missing-exit':
                return
            if mode == 'empty-event':
                yield p.ExecSandboxEvent()
                return
            yield p.ExecSandboxEvent(stderr={'data': b'err'})
            yield p.ExecSandboxEvent(exit={'exit_code': 7})
            if mode == 'after-exit':
                yield p.ExecSandboxEvent(stdout={'data': b'late'})
        finally:
            state.stopped.set()
    handler = grpc.method_handlers_generic_handler('openshell.v1.OpenShell', {
        'ExecSandbox': grpc.unary_stream_rpc_method_handler(execute,
            request_deserializer=p.ExecSandboxRequest.FromString,
            response_serializer=p.ExecSandboxEvent.SerializeToString)})
    server = grpc.aio.server(options=options)
    server.add_generic_rpc_handlers((handler,))
    credentials = grpc.ssl_server_credentials(
        [((material / 'server.key').read_bytes(), (material / 'server.pem').read_bytes())],
        root_certificates=(material / 'ca.pem').read_bytes(), require_client_auth=True)
    port = server.add_secure_port('127.0.0.1:0', credentials)
    assert port
    await server.start()
    try:
        yield mtls_config(material, f'https://localhost:{port}'), p, state
    finally:
        await server.stop(None)


def test_stock_generated_fixture_request_id_and_single_dispatch(mtls_material, monkeypatch):
    # Hostile service configuration must not reach the channel's fixed options.
    monkeypatch.setenv('GRPC_SERVICE_CONFIG', '{"methodConfig":[{"name":[{}],"retryPolicy":{"maxAttempts":5}}]}')
    async def scenario():
        async with stock_server(mtls_material) as (config, p, state):
            async with stock_exec_channel(config, p) as channel:
                lease = str(uuid4())
                allowance = ot.CallerAllowance(model.bound(1))
                session = channel.bind_lease(lease, model.GEN, local_owner_id='journal-owner')
                request = p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker'], stdin=b'synthetic', no_login_shell=True)
                result = await session.execute(request, allowance, attempt=1, output_cap_bytes=6, message_cap=3)
                assert (result.stdout, result.stderr, result.exit_code) == (b'out', b'err', 7)
                assert len(state.calls) == 1
                sent = state.calls[0]
                assert sent.sandbox == model.GEN and sent.stdin == b'synthetic'
                assert sent.request_id == ot.exec_request_id(lease, 1)
                assert UUID(sent.request_id).int != 0
                assert 0 < state.deadlines[0] <= 1.1  # gRPC rounds encoded relative deadlines.
                assert sent.execution_timeout.ToNanoseconds() > 0
                for another in (session, channel.bind_lease(lease, model.GEN, local_owner_id='journal-owner')):
                    with pytest.raises(ot.TransportError, match='not_repeatable'):
                        await another.execute(request, ot.CallerAllowance(model.bound()), attempt=2,
                                              output_cap_bytes=6, message_cap=3)
                assert len(state.calls) == 1
                assert request.request_id == '' and request.sandbox == ''
    model.run(scenario())


@pytest.mark.parametrize('mode', ['drop', 'drop-after-output', 'missing-exit', 'empty-event', 'after-exit', 'silence', 'cancel', 'outer-cancel', 'bytes', 'messages'])
def test_stock_stream_faults_are_bounded_and_never_replayed(mtls_material, mode):
    async def scenario():
        async with stock_server(mtls_material, mode=mode if mode in ('drop', 'drop-after-output', 'missing-exit', 'empty-event', 'after-exit', 'silence') else 'silence' if 'cancel' in mode else 'normal') as (config, p, state):
            async with stock_exec_channel(config, p) as channel:
                lease = str(uuid4())
                session = channel.bind_lease(lease, model.GEN, local_owner_id='journal-owner')
                allowance = ot.CallerAllowance(model.bound(.18))
                request = p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker'])
                task = asyncio.create_task(session.execute(request, allowance, attempt=1,
                    output_cap_bytes=2 if mode == 'bytes' else 100,
                    message_cap=1 if mode == 'messages' else 10))
                await asyncio.wait_for(state.entered.wait(), 1)
                if mode == 'cancel': allowance.cancelled.set()
                if mode == 'outer-cancel': task.cancel()
                with pytest.raises(asyncio.CancelledError if mode == 'outer-cancel' else ot.TransportError) as error:
                    await asyncio.wait_for(task, 1)
                assert 'SECRET' not in str(error.value)
                with pytest.raises(ot.TransportError, match='not_repeatable'):
                    await session.execute(request, ot.CallerAllowance(model.bound()), attempt=2,
                                          output_cap_bytes=100, message_cap=10)
                assert len(state.calls) == 1
    model.run(scenario())


def test_stock_kill_race_invalidates_every_handle(mtls_material):
    async def scenario():
        async with stock_server(mtls_material, mode='silence') as (config, p, state):
            async with stock_exec_channel(config, p) as channel:
                lease = str(uuid4())
                session = channel.bind_lease(lease, model.GEN, local_owner_id='journal-owner')
                other = channel.bind_lease(lease, model.GEN, local_owner_id='journal-owner')
                task = asyncio.create_task(session.execute(p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker']),
                    ot.CallerAllowance(model.bound(1)), attempt=1, output_cap_bytes=100, message_cap=10))
                await asyncio.wait_for(state.entered.wait(), 1)
                other.invalidate()
                with pytest.raises((ot.TransportError, asyncio.CancelledError)):
                    await asyncio.wait_for(task, .5)
                assert len(state.calls) == 1
    model.run(scenario())


def test_stock_single_dispatch_with_hostile_retry_service_config(mtls_material, monkeypatch):
    import json
    grpc = pytest.importorskip('grpc')
    original = grpc.aio.secure_channel
    hostile = json.dumps({'methodConfig': [{'name': [{'service': 'openshell.v1.OpenShell'}],
        'retryPolicy': {'maxAttempts': 5, 'initialBackoff': '0.01s', 'maxBackoff': '0.01s',
                        'backoffMultiplier': 1, 'retryableStatusCodes': ['UNAVAILABLE']}}]})
    observed = []
    def construct(target, credentials, *, options):
        observed.append(dict(options))
        # Simulate resolver/service-config injection below the public factory.
        poisoned = [(key, hostile if key == 'grpc.service_config' else value) for key, value in options]
        return original(target, credentials, options=poisoned)
    monkeypatch.setattr(grpc.aio, 'secure_channel', construct)
    async def scenario():
        async with stock_server(mtls_material, mode='drop') as (config, p, state):
            async with stock_exec_channel(config, p) as channel:
                session = channel.bind_lease(str(uuid4()), model.GEN, local_owner_id='journal-owner')
                with pytest.raises(ot.TransportError):
                    await session.execute(p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker']),
                        ot.CallerAllowance(model.bound(1)), attempt=1, output_cap_bytes=100, message_cap=10)
                assert len(state.calls) == 1
        assert observed[0]['grpc.enable_retries'] == 0
        assert observed[0]['grpc.service_config_disable_resolution'] == 1
        assert observed[0]['grpc.service_config'] == '{}'
        assert observed[0]['grpc.enable_http_proxy'] == 0
    model.run(scenario())


def test_stock_invalid_or_oversize_input_never_dispatches(mtls_material):
    async def scenario():
        async with stock_server(mtls_material) as (config, p, state):
            async with stock_exec_channel(config, p) as channel:
                session = channel.bind_lease(str(uuid4()), model.GEN, local_owner_id='journal-owner')
                request = p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, stdin=b'x' * (4 * 1024 * 1024))
                with pytest.raises(ot.TransportError, match='input_limit'):
                    await session.execute(request, ot.CallerAllowance(model.bound()), attempt=1,
                                          output_cap_bytes=100, message_cap=10)
                with pytest.raises(ot.TransportError, match='local_owner'):
                    channel.bind_lease(str(uuid4()), model.GEN, local_owner_id='cert-owner')
                assert not state.calls
    model.run(scenario())
