"""Generated SDK over private local UDS; NOT the Rust server or physical qualification."""

import asyncio
from contextlib import asynccontextmanager
import importlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import traceback

import pytest

from phase_loop_runtime import openshell_transport as ot
import test_openshell_transport as model


@pytest.fixture
def sdk():
    proto = model.generated_bindings()
    return SimpleNamespace(proto=proto, grpc=importlib.import_module("grpc"),
                           service=importlib.import_module("openshell_pb2_grpc"))


@asynccontextmanager
async def local_server(sdk):
    p, grpc = sdk.proto, sdk.grpc
    state = SimpleNamespace(calls=[], paths=[], hold=None, failure=None, created=False,
                            fenced=False, barrier=False, destruction_pending=False, entered=asyncio.Event(), stopped=asyncio.Event())

    class Paths(grpc.aio.ServerInterceptor):
        async def intercept_service(self, continuation, details):
            state.paths.append(details.method)
            return await continuation(details)

    async def receive(operation, request, context):
        state.calls.append((operation, request.SerializeToString(deterministic=True)))
        if state.failure is not None:
            await context.abort(state.failure, "SECRET remote diagnostics")
        if state.hold == operation:
            state.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                state.stopped.set()

    class Service(sdk.service.OpenShellServicer):
        async def ControlCancellationLease(self, request, context):
            await receive(request.operation, request, context)
            if request.operation == 2:
                state.created = True
                return p.ControlCancellationLeaseResponse(
                    sandbox={"metadata": {"id": model.GEN, "workspace": "dedicated"}})
            if request.operation == 3:
                state.fenced = True
                state.barrier = not state.destruction_pending
                return p.ControlCancellationLeaseResponse(barrier_confirmed=state.barrier)
            if request.operation == 4:
                return p.ControlCancellationLeaseResponse(entries=[] if state.barrier else [
                    {"lease_id": "lease", "sandbox_ref": model.GEN}])
            if request.operation == 5:
                if not state.created and not state.fenced:
                    await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "unreserved lease")
                return p.ControlCancellationLeaseResponse(
                    lease={"lease_id": "lease", "sandbox_ref": model.GEN if state.created else "reservation:lease"},
                    admission_ready=not state.fenced, create_settled=True,
                    fenced=state.fenced, destruction_observed=state.barrier and state.created,
                    cleanup_pending=not state.barrier, barrier_confirmed=state.barrier)
            return p.ControlCancellationLeaseResponse()

        async def ExecCancellationLease(self, request, context):
            await receive("exec", request, context)
            yield p.ExecSandboxEvent(stdout={"data": b"out"})
            yield p.ExecSandboxEvent(stderr={"data": b"err"})
            yield p.ExecSandboxEvent(exit={"exit_code": 7})

    # tempfile creates a private 0700 directory; keep the UDS path below OS limits.
    with tempfile.TemporaryDirectory(prefix="ot-r13-") as directory:
        address = "unix:" + str(Path(directory) / "rpc.sock")
        server = grpc.aio.server(interceptors=[Paths()])
        sdk.service.add_OpenShellServicer_to_server(Service(), server)
        assert server.add_insecure_port(address)
        await server.start()
        # No service config, resolver config, interceptors or retry policy.
        channel = grpc.aio.insecure_channel(address, options=[("grpc.enable_retries", 0)])
        try:
            await asyncio.wait_for(channel.channel_ready(), 3)
            client = ot.LeaseSession(p, sdk.service.OpenShellStub(channel), workspace="dedicated",
                                     owner_id="owner", lease_id="lease", fresh=True)
            yield client, state
        finally:
            await channel.close()
            await server.stop(None)


def create_request(p):
    return p.CreateSandboxRequest(spec={"restart_policy": 1, "policy": {}})


async def ready(client, p):
    await client.create(create_request(p), model.bound())
    await client.status(model.bound())


def test_compact_fields_match_generated_schema(sdk):
    compact = model.bindings()
    seen = set()

    def compare(left, right):
        if (left.full_name, right.full_name) in seen:
            return
        seen.add((left.full_name, right.full_name))
        assert left.GetOptions().map_entry == right.GetOptions().map_entry
        for field in left.fields:
            actual = right.fields_by_name[field.name]
            assert field.number == actual.number, field.full_name
            assert field.is_repeated == actual.is_repeated, field.full_name
            # The compact fixture represents only these enums with int32 wire values.
            if field.name in ("operation", "restart_policy"):
                assert (field.type, actual.type) == (field.TYPE_INT32, field.TYPE_ENUM)
            else:
                assert field.type == actual.type, field.full_name
            if field.containing_oneof:
                assert actual.containing_oneof.name == field.containing_oneof.name
            if field.message_type:
                compare(field.message_type, actual.message_type)

    for name in ("ControlCancellationLeaseRequest", "ControlCancellationLeaseResponse",
                 "ExecCancellationLeaseRequest", "ExecSandboxEvent",
                 "SourceCancellationLeaseRequest", "SourceCancellationLeaseResponse"):
        compare(getattr(compact, name).DESCRIPTOR, getattr(sdk.proto, name).DESCRIPTOR)
    operation = sdk.proto.ControlCancellationLeaseRequest.DESCRIPTOR.fields_by_name["operation"].enum_type
    assert {v.name: v.number for v in operation.values} == {
        "OPERATION_UNSPECIFIED": 0, "OPERATION_ENROLL": 1, "OPERATION_CREATE": 2,
        "OPERATION_KILL": 3, "OPERATION_LIST": 4, "OPERATION_STATUS": 5}


def test_generated_paths_and_serialized_fields(sdk):
    async def scenario():
        p = sdk.proto
        async with local_server(sdk) as (client, state):
            await client.enroll(model.bound(0.75))
            create = create_request(p)
            create.name = "ignored-name"
            create.request_id = model.GEN
            await client.create(create, model.bound(0.75))
            await client.status(model.bound(0.75))
            execute = p.ExecSandboxRequest(
                sandbox="ignored-sandbox", command=["packaged-worker", "arg"], stdin=b"synthetic-input",
                workdir="/work", environment={"SYNTHETIC": "value"}, execution_timeout={"seconds": 9},
                no_login_shell=True, request_id=model.GEN)
            result = await client.execute(execute, model.bound(0.75), output_cap_bytes=6)
            assert (result.stdout, result.stderr, result.exit_code) == (b"out", b"err", 7)
            assert await client.list_owned(model.bound(0.75)) == ((model.GEN, "lease"),)
            await client.kill(model.bound(0.75))
            assert await client.list_owned(model.bound(0.75)) == ()
            assert [op for op, _ in state.calls] == [1, 2, 5, "exec", 4, 3, 5, 4]
            expected_create = p.CreateSandboxRequest()
            expected_create.CopyFrom(create)
            expected_create.name = ""
            expected_create.workspace_scope.workspace = "dedicated"
            expected_create.await_main_process_attachment = True
            expected_exec = p.ExecSandboxRequest()
            expected_exec.CopyFrom(execute)
            expected_exec.sandbox = model.GEN
            expected_exec.workspace_scope.workspace = "dedicated"
            for index, (op, wire) in enumerate(state.calls):
                cls = p.ExecCancellationLeaseRequest if op == "exec" else p.ControlCancellationLeaseRequest
                decoded = cls.FromString(wire)
                fields = dict(workspace_scope={"workspace": "dedicated"}, owner_id="owner", lease_id="lease",
                              bound={"nanos": 750000000})
                if index == 6:  # KILL's STATUS uses only the remaining bound.
                    assert 0 < decoded.bound.ToNanoseconds() <= 750000000
                    fields["bound"] = decoded.bound
                expected = cls(**fields)
                if op == "exec":
                    expected.exec.CopyFrom(expected_exec)
                else:
                    expected.operation = op
                    if op == 2:
                        expected.create.CopyFrom(expected_create)
                assert decoded == expected
                assert wire == expected.SerializeToString(deterministic=True)
                method = "ExecCancellationLease" if op == "exec" else "ControlCancellationLease"
                assert state.paths[index] == f"/openshell.v1.OpenShell/{method}"
            assert create.name == "ignored-name" and execute.sandbox == "ignored-sandbox"
    model.run(scenario())


@pytest.mark.parametrize("operation", [1, 2, 3, 4, 5, "exec"])
@pytest.mark.parametrize("stop", ["deadline", "bound_cancel", "outer_cancel"])
def test_real_calls_stop_once_without_retry(sdk, operation, stop):
    async def scenario():
        p = sdk.proto
        async with local_server(sdk) as (client, state):
            if operation != 2:
                await ready(client, p)
            state.calls.clear()
            state.paths.clear()
            state.hold = operation
            bound = model.bound(0.25 if stop == "deadline" else 3)
            if operation == "exec":
                call = client.execute(p.ExecSandboxRequest(), bound, output_cap_bytes=0)
            elif operation == 2:
                call = client.create(create_request(p), bound)
            else:
                call = getattr(client, {1: "enroll", 3: "kill", 4: "list_owned", 5: "status"}[operation])(bound)
            task = asyncio.create_task(call)
            await asyncio.wait_for(state.entered.wait(), 2)
            if stop == "outer_cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                if stop == "bound_cancel":
                    bound.cancelled.set()
                with pytest.raises(ot.TransportError, match="sandbox_placement_operation_timeout"):
                    await task
            await asyncio.wait_for(state.stopped.wait(), 2)
            if operation == 2:
                with pytest.raises(ot.TransportError, match="create_not_repeatable"):
                    await client.create(create_request(p), model.bound())
            if operation == "exec":
                with pytest.raises(ot.TransportError, match="execute_not_permitted"):
                    await client.execute(p.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
            if operation == 5:
                assert client._poisoned == (stop != "outer_cancel")
            assert [op for op, _ in state.calls] == [operation]
            assert len(state.paths) == 1
    model.run(scenario())


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status,code", [
    ("DEADLINE_EXCEEDED", "sandbox_placement_operation_timeout"),
    ("PERMISSION_DENIED", "owner_workspace_refused"), ("UNAUTHENTICATED", "owner_workspace_refused"),
    ("FAILED_PRECONDITION", "transition_refused"), ("INVALID_ARGUMENT", "invalid_request"),
    ("ABORTED", "cas_conflict"), ("UNAVAILABLE", "authority_unavailable"),
])
def test_actual_aio_rpc_error_mapping(sdk, stream, status, code):
    async def scenario():
        async with local_server(sdk) as (client, state):
            await ready(client, sdk.proto)
            state.calls.clear()
            state.failure = getattr(sdk.grpc.StatusCode, status)
            with pytest.raises(ot.TransportError, match=f"^{code}$") as caught:
                if stream:
                    await client.execute(sdk.proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
                else:
                    await client.status(model.bound())
            error = caught.value
            assert error.uncertain and error.__suppress_context__
            assert isinstance(error.__context__, sdk.grpc.aio.AioRpcError)
            assert error.__context__.code() == state.failure
            assert "SECRET" in error.__context__.details()  # R12-L3 remains an explicit logging limit.
            assert "SECRET" not in "".join(traceback.format_exception(error))
            assert [op for op, _ in state.calls] == ["exec" if stream else 5]
    model.run(scenario())


def test_status_before_create_refusal_stays_poisoned_with_cleanup(sdk):
    async def scenario():
        async with local_server(sdk) as (client, state):
            with pytest.raises(ot.TransportError, match="transition_refused") as caught:
                await client.status(model.bound())
            assert isinstance(caught.value.__context__, sdk.grpc.aio.AioRpcError)
            await ready(client, sdk.proto)
            with pytest.raises(ot.TransportError, match="execute_not_permitted"):
                await client.execute(sdk.proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
            await client.kill(model.bound())
            assert await client.list_owned(model.bound()) == ()
            assert [op for op, _ in state.calls] == [5, 2, 5, 3, 5, 4]
    model.run(scenario())


def test_pending_fence_stays_in_list_until_barrier(sdk):
    async def scenario():
        async with local_server(sdk) as (client, state):
            await ready(client, sdk.proto)
            state.destruction_pending = True
            with pytest.raises(ot.TransportError, match="operation_timeout"):
                await client.kill(model.bound())
            assert state.fenced and not state.barrier
            assert await client.list_owned(model.bound()) == ((model.GEN, "lease"),)
            state.destruction_pending = False
            await client.kill(model.bound())
            assert state.barrier
            assert await client.list_owned(model.bound()) == ()
    asyncio.run(scenario())


def test_split_dispatch_real_stream_outlives_dispatch_budget(sdk):
    async def scenario():
        async with local_server(sdk) as (client, state):
            await ready(client, sdk.proto)
            state.hold = "exec"
            handle = await client.dispatch(sdk.proto.ExecSandboxRequest(), model.bound(.05),
                                           stream_bound=model.bound(1), output_cap_bytes=6, message_cap=3)
            await asyncio.wait_for(state.entered.wait(), .5)
            assert await handle.wait(.08) is None
            assert len([op for op, _ in state.calls if op == "exec"]) == 1
            handle.cancel()
            with pytest.raises(ot.TransportError, match="operation_timeout"):
                await handle.wait(0)
            await asyncio.wait_for(state.stopped.wait(), .5)
    asyncio.run(scenario())


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
