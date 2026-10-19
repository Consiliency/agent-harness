"""Actual protobuf/gRPC on private local UDS, never Rust authority or VM proof."""
import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace

import pytest

from phase_loop_runtime import openshell_backend as ob, placement_lease as journal
from phase_loop_runtime.openshell_channel import _ScopedStub
from phase_loop_runtime.openshell_artifacts import Limits, Refused, SourceFile
from phase_loop_runtime.review_stage import review_tree_manifest_sha256
from phase_loop_runtime.sandbox_placement import OperationBound, PlacementUnavailable
from test_openshell_backend import pipeline as pipeline
from test_openshell_artifacts import bound as bound, bundle as bundle, limits as limits, repository as repository
from test_openshell_transport_grpc import sdk as sdk
import test_openshell_transport as model


@pytest.fixture
def rpc(pipeline, sdk):
    backend, endpoint, _, _, _, leases, _, _, prepared, request = pipeline
    loop = backend._bridge._loop
    state = SimpleNamespace(calls=[], deadlines=[], client_bounds=[], fail=None, hold=None, mismatch=None,
                            entered=threading.Event(), stopped=threading.Event(), digest=None,
                            published=False, delay=0)
    p = sdk.proto

    class Service(sdk.service.OpenShellServicer):
        async def ControlCancellationLease(self, request, context):
            return await endpoint.ControlCancellationLease(request, timeout=context.time_remaining())

        async def SourceCancellationLease(self, request, context):
            operation = request.WhichOneof('operation')
            state.calls.append(request)
            state.deadlines.append(context.time_remaining())
            await asyncio.sleep(state.delay)
            if operation == 'begin':
                state.digest = request.begin.digest
            if operation == 'commit':
                state.published = True  # Model effect before possible lost reply.
            if state.fail == operation:
                await context.abort(sdk.grpc.StatusCode.UNKNOWN, 'private diagnostics')
            if state.hold == operation:
                state.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    state.stopped.set()
            generation = model.GEN
            digest = state.digest if operation == 'commit' else b''
            if state.mismatch == (operation, 'generation'):
                generation = '00000000-0000-0000-0000-000000000001'
            if state.mismatch == (operation, 'digest'):
                digest = b'X' * 32
            return p.SourceCancellationLeaseResponse(generation=generation, digest=digest)

    with tempfile.TemporaryDirectory(prefix='source-r72-') as temp:
        async def start():
            server = sdk.grpc.aio.server()
            sdk.service.add_OpenShellServicer_to_server(Service(), server)
            address = 'unix:' + str(Path(temp) / 'rpc.sock')
            assert server.add_insecure_port(address)
            await server.start()
            channel = sdk.grpc.aio.insecure_channel(address, options=[('grpc.enable_retries', 0)])
            await asyncio.wait_for(channel.channel_ready(), 3)
            raw = sdk.service.OpenShellStub(channel)
            source_call = raw.SourceCancellationLease
            def source(request, **kwargs):
                state.client_bounds.append(kwargs['timeout'])
                return source_call(request, **kwargs)
            raw.SourceCancellationLease = source
            return server, channel, _ScopedStub(raw,
                                               SimpleNamespace(workspace='model', owner_id=journal.owner_id()))
        server, channel, stub = asyncio.run_coroutine_threadsafe(start(), loop).result(5)
        backend._stub = stub
        stage = ob.SourceRpcStage()
        backend._stage = stage
        lease = journal.open_lease('openshell', 'openshell://model.invalid/workspace')
        leases.append(lease)
        backend.bind_live_lease(lease)
        request = replace(request, owner_id=lease.owner_id, lease_id=lease.lease_id)
        backend.admit(request, model.bound())
        assert stage._session is backend._session
        try:
            yield SimpleNamespace(backend=backend, stage=stage, lease=lease, state=state,
                                  prepared=prepared, request=request, endpoint=endpoint)
        finally:
            async def stop():
                await channel.close()
                await server.stop(None)
            asyncio.run_coroutine_threadsafe(stop(), loop).result(5)


def commit(rpc, bound=None):
    return rpc.backend.commit(rpc.prepared, rpc.request, bound or model.bound())


def assert_no_replay(rpc):
    count = len(rpc.state.calls)
    assert rpc.lease.fenced and rpc.lease.path.exists()
    assert not rpc.backend._committed and 'exec' not in rpc.endpoint.calls
    with pytest.raises((Refused, ValueError)):
        commit(rpc)
    assert len(rpc.state.calls) == count


def test_exact_wire_and_canonical_receipt(rpc, repository):
    receipt = commit(rpc, model.bound(60))
    source = rpc.backend._bundle
    wire = rpc.state.calls
    assert [r.WhichOneof('operation') for r in wire] == ['begin', 'chunk', 'chunk', 'commit']
    expected = bytes.fromhex(review_tree_manifest_sha256(repository[0]))
    assert wire[0].begin.digest == expected
    assert expected.hex() != source.sha256
    for actual, entry in zip(wire[0].begin.files, source.files, strict=True):
        assert (actual.path, actual.size, actual.sha256, actual.executable) == (
            entry.path, len(entry.data), hashlib.sha256(entry.data).digest(), entry.mode == 0o100755)
    for index, actual in enumerate(wire[1:-1]):
        assert (actual.chunk.file, actual.chunk.offset, actual.chunk.data) == (index, 0, source.files[index].data)
    for actual in wire:
        assert (actual.workspace_scope.workspace, actual.owner_id, actual.lease_id, actual.generation) == (
            'model', rpc.lease.owner_id, rpc.lease.lease_id, model.GEN)
    assert wire[-1].commit is True
    assert receipt.sandbox_ref == model.GEN
    assert receipt.snapshot_sha256 == source.sha256
    assert rpc.backend._committed and rpc.lease.path.exists()
    assert rpc.endpoint.calls == [2, 5]  # No enrollment or second CREATE.
    assert all(0 < n <= 30 for n in rpc.state.client_bounds)
    assert all(n > 0 for n in rpc.state.deadlines)  # gRPC rounds wire deadlines.
    with pytest.raises(Refused, match='commit_not_repeatable'):
        commit(rpc)


@pytest.mark.parametrize('operation', ['begin', 'chunk', 'commit'])
def test_uncertain_effect_no_replay_retains_journal(rpc, operation):
    rpc.state.fail = operation
    with pytest.raises(ob.TransportError) as error:
        commit(rpc)
    assert error.value.uncertain
    assert rpc.state.calls[-1].WhichOneof('operation') == operation
    assert rpc.state.published == (operation == 'commit')
    assert_no_replay(rpc)
    rpc.endpoint.pending = True
    with pytest.raises(ob.TransportError):
        rpc.backend.kill(rpc.lease.lease_id, model.bound())
    assert rpc.lease.path.exists()


@pytest.mark.parametrize('operation', ['begin', 'chunk', 'commit'])
@pytest.mark.parametrize('field', ['generation', 'digest'])
def test_response_mismatch_fences(rpc, operation, field):
    rpc.state.mismatch = operation, field
    with pytest.raises(ob.TransportError, match='stage_binding_mismatch'):
        commit(rpc)
    assert rpc.state.calls[-1].WhichOneof('operation') == operation
    assert_no_replay(rpc)


@pytest.mark.parametrize('operation', ['begin', 'chunk', 'commit'])
@pytest.mark.parametrize('stop', ['timeout', 'cancel', 'kill'])
def test_inflight_stop_never_replays(rpc, operation, stop):
    rpc.state.hold = operation
    cancelled = threading.Event()
    errors = []
    def run():
        try:
            commit(rpc, OperationBound(.25 if stop == 'timeout' else 2, cancelled))
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert rpc.state.entered.wait(2)
        if stop == 'cancel':
            cancelled.set()
        elif stop == 'kill':
            rpc.backend.kill(rpc.lease.lease_id, model.bound())
        thread.join(1)
        assert not thread.is_alive()
        assert errors and isinstance(errors[0], (Refused, ob.TransportError, PlacementUnavailable))
        assert rpc.state.stopped.wait(1)
        assert_no_replay(rpc)
    finally:
        cancelled.set()
        thread.join(3)


@pytest.mark.parametrize('bad', ['order', 'duplicate', 'trailing-dot', 'path-length', 'total', 'files', 'message'])
def test_malformed_or_cap_before_effect(rpc, bad):
    source = rpc.backend._bundle
    files = source.files
    if bad == 'order':
        files = tuple(reversed(files))
    elif bad == 'duplicate':
        files = (files[0], files[0])
    elif bad == 'trailing-dot':
        files = (replace(files[0], path='a.'),)
    elif bad == 'path-length':
        files = (replace(files[0], path='a' * 1025),)
    elif bad == 'total':
        files = (replace(files[0], data=b'x' * (4 * 1024 * 1024 + 1)),)
    elif bad == 'files':
        files = tuple(SourceFile(f'f{i:04}', 0o100644, b'') for i in range(1025))
    else:
        files = tuple(SourceFile(f'{i:04}' + 'a' * 1020, 0o100644, b'') for i in range(1024))
    source = replace(source, files=files, limits=Limits(5000000, 5000000, 2000, 1, 1))
    rpc.backend._bundle = source
    rpc.backend._binding = replace(rpc.backend._binding, source_sha256=source.sha256)
    rpc.request = replace(rpc.request, snapshot_sha256=source.sha256)
    rpc.prepared = replace(rpc.prepared, snapshot_sha256=source.sha256)
    with pytest.raises(Refused):
        commit(rpc)
    assert not rpc.state.calls
    assert_no_replay(rpc)


def test_chunk_boundaries_empty_and_executable(rpc, repository):
    source = rpc.backend._bundle
    files = (SourceFile('other.txt', 0o100644, b''),
             SourceFile('owned.txt', 0o100755, bytes(range(256)) * 257))
    source = replace(source, files=files, limits=Limits(100000, 100000, 20, 1, 1))
    for entry in files:
        path = repository[0] / entry.path
        path.write_bytes(entry.data)
        path.chmod(entry.mode & 0o777)
    rpc.backend._bundle = source
    rpc.backend._binding = replace(rpc.backend._binding, source_sha256=source.sha256)
    rpc.request = replace(rpc.request, snapshot_sha256=source.sha256)
    rpc.prepared = replace(rpc.prepared, snapshot_sha256=source.sha256)
    commit(rpc)
    calls = rpc.state.calls
    assert calls[0].begin.digest.hex() == review_tree_manifest_sha256(repository[0])
    assert calls[0].begin.files[1].executable
    assert [(r.chunk.file, r.chunk.offset, len(r.chunk.data)) for r in calls[1:-1]] == [
        (1, 0, 65536), (1, 65536, 256)]
    assert b''.join(r.chunk.data for r in calls[1:-1]) == files[1].data


@pytest.mark.parametrize('field', ['workspace', 'owner_id', 'lease_id', 'generation', 'source_sha256'])
def test_wrong_binding_before_effect(rpc, field):
    rpc.backend._binding = replace(rpc.backend._binding, **{field: 'wrong'})
    with pytest.raises(Refused, match='source_binding_invalid'):
        commit(rpc)
    assert not rpc.state.calls
    assert_no_replay(rpc)


def test_pre_cancelled_before_effect(rpc):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(Refused, match='cancelled'):
        commit(rpc, OperationBound(1, cancelled))
    assert not rpc.state.calls
    # No coroutine ran; backend's consumed attempt still prevents replay.
    with pytest.raises(Refused, match='commit_not_repeatable'):
        commit(rpc)


def test_responses_do_not_extend_fixed_caller_bound(rpc):
    rpc.state.delay = .06
    with pytest.raises((Refused, ob.TransportError, PlacementUnavailable)):
        commit(rpc, model.bound(.15))
    assert 1 < len(rpc.state.calls) < 4
    assert all(a > b for a, b in zip(rpc.state.client_bounds, rpc.state.client_bounds[1:]))
    assert_no_replay(rpc)


def test_successful_kill_and_list_do_not_clear_journal_in_adapter(rpc):
    rpc.state.fail = 'commit'
    with pytest.raises(ob.TransportError):
        commit(rpc)
    rpc.backend.kill(rpc.lease.lease_id, model.bound())
    assert rpc.backend.list_owned(rpc.lease.owner_id, model.bound()) == ()
    assert rpc.endpoint.calls[-3:] == [3, 5, 4]
    assert rpc.lease.path.exists()  # Clearing belongs to the driver/reaper only.
