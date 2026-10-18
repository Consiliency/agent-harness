"""Modeled client falsifiers, NOT physical OpenShell conformance.

The compact protobuf descriptor retains the private envelope field numbers.
Public nested messages are test doubles, not a generated public API; deployment must supply full
generated bindings from the reviewed server revision, not this test fixture.
"""

import asyncio
from types import SimpleNamespace
import threading
from uuid import uuid4

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf import duration_pb2
import pytest

from phase_loop_runtime import openshell_transport as ot
from phase_loop_runtime.sandbox_placement import OperationBound


def bindings():
    file = descriptor_pb2.FileDescriptorProto(name="private_fixture.proto", package="openshell.v1", syntax="proto3")
    file.dependency.append("google/protobuf/duration.proto")
    # name, field number, scalar type/message name, repeated
    schemas = {
        "Workspace": [("workspace", 1, "string", False)],
        "Meta": [("id", 1, "string", False), ("workspace", 7, "string", False)],
        "Filesystem": [("read_only", 2, "string", True), ("read_write", 3, "string", True)],
        "Policy": [("filesystem", 2, "Filesystem", False), ("network_policies", 5, "string", True)],
        "Template": [("agent_socket", 3, "string", False), ("environment", 6, "string", True),
                     ("driver_config", 11, "Meta", False)],
        "Spec": [("environment", 5, "string", True), ("template", 6, "Template", False),
                 ("policy", 7, "Policy", False), ("providers", 8, "string", True),
                 ("command", 12, "string", True), ("restart_policy", 15, "int32", False)],
        "Sandbox": [("metadata", 1, "Meta", False), ("spec", 2, "Spec", False)],
        "CreateSandboxRequest": [("spec", 1, "Spec", False), ("name", 2, "string", False),
                                 ("await_main_process_attachment", 5, "bool", False),
                                 ("workload_template", 6, "string", False),
                                 ("workspace_scope", 7, "Workspace", False),
                                 ("request_id", 8, "string", False), ("service_exposures", 9, "string", True)],
        "ExecSandboxRequest": [("sandbox", 1, "string", False), ("command", 2, "string", True),
                               ("stdin", 6, "bytes", False), ("tty", 7, "bool", False),
                               ("request_id", 11, "string", False), ("workspace_scope", 12, "Workspace", False)],
        "CancellationLeaseEntry": [("lease_id", 1, "string", False), ("sandbox_ref", 2, "string", False)],
        "ControlCancellationLeaseRequest": [("workspace_scope", 1, "Workspace", False),
                                            ("owner_id", 2, "string", False), ("lease_id", 3, "string", False),
                                            ("operation", 4, "int32", False), ("bound", 5, "Duration", False),
                                            ("create", 6, "CreateSandboxRequest", False)],
        "ControlCancellationLeaseResponse": [("entries", 1, "CancellationLeaseEntry", True),
                                             ("sandbox", 2, "Sandbox", False), ("barrier_confirmed", 3, "bool", False),
                                             ("lease", 4, "CancellationLeaseEntry", False)] +
            [(name, num, "bool", False) for num, name in enumerate(
                ("admission_ready", "create_settled", "execution_claimed", "fenced", "destruction_observed", "cleanup_pending"), 5)],
        "ExecCancellationLeaseRequest": [("workspace_scope", 1, "Workspace", False),
                                         ("owner_id", 2, "string", False), ("lease_id", 3, "string", False),
                                         ("bound", 4, "Duration", False), ("exec", 5, "ExecSandboxRequest", False)],
        "Output": [("data", 1, "bytes", False)],
        "Exit": [("exit_code", 1, "int32", False)],
        "ExecSandboxEvent": [("stdout", 1, "Output", False), ("stderr", 2, "Output", False), ("exit", 3, "Exit", False)],
    }
    types = {"string": 9, "bytes": 12, "bool": 8, "int32": 5}
    for name, fields in schemas.items():
        msg = file.message_type.add(name=name)
        if name == "ExecSandboxEvent":
            msg.oneof_decl.add(name="payload")
        for key, number, kind, repeated in fields:
            f = msg.field.add(name=key, number=number, label=3 if repeated else 1,
                              type=types.get(kind, 11))
            if kind not in types:
                f.type_name = ".google.protobuf.Duration" if kind == "Duration" else f".openshell.v1.{kind}"
            if name == "ExecSandboxEvent":
                f.oneof_index = 0
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(duration_pb2.DESCRIPTOR.serialized_pb)
    pool.Add(file)
    return SimpleNamespace(**{name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"openshell.v1.{name}"))
                              for name in schemas})


P = bindings()
GEN = str(uuid4())


def bound(seconds=1):
    return OperationBound(seconds, threading.Event())


def observation(**kw):
    fields = dict(lease={"lease_id": "lease", "sandbox_ref": GEN}, admission_ready=True,
                  create_settled=True, cleanup_pending=True)
    fields.update(kw)
    return P.ControlCancellationLeaseResponse(**fields)


def create_request():
    return P.CreateSandboxRequest(spec={"restart_policy": 1, "policy": {}})


class RpcFailure(Exception):
    def __init__(self, name):
        super().__init__("SECRET remote diagnostics")
        self.name = name

    def code(self):
        return SimpleNamespace(name=self.name)


class Stream:
    def __init__(self, events):
        self.events = iter(events)
        self.cancelled = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = next(self.events, None)
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return await item()
        return item

    def cancel(self):
        self.cancelled = True


class Stub:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.events = [P.ExecSandboxEvent(exit={"exit_code": 0})]
        self.stream = None

    async def ControlCancellationLease(self, request, *, timeout):
        # Round-trip real protobuf bytes, never persist credential-bearing EXEC.
        req = P.ControlCancellationLeaseRequest.FromString(request.SerializeToString())
        self.calls.append((req.operation, req, timeout))
        response = self.responses.get(req.operation, P.ControlCancellationLeaseResponse())
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return await response(req)
        return response

    def ExecCancellationLease(self, request, *, timeout):
        self.calls.append(("exec", request, timeout))
        self.stream = Stream(self.events)
        return self.stream


def session(stub, **kw):
    return ot.LeaseSession(P, stub, workspace="dedicated", owner_id="owner", lease_id="lease", **kw)


def run(coro):
    return asyncio.run(coro)


def test_mapping_enroll_create_status_exec_list():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[2] = P.ControlCancellationLeaseResponse(sandbox={"metadata": {"id": GEN, "workspace": "dedicated"}})
        stub.responses[5] = observation()
        stub.responses[4] = P.ControlCancellationLeaseResponse(entries=[{"lease_id": "lease", "sandbox_ref": GEN}])
        await client.enroll(bound())
        request = create_request()
        request.name = "caller-name"
        assert await client.create(request, bound(0.75)) == GEN
        assert request.name == "caller-name"
        assert (await client.status(bound())).admission_ready
        payload = P.ExecSandboxRequest(stdin=b"SECRET", command=["packaged-worker"], sandbox="wrong")
        stub.events = [P.ExecSandboxEvent(stdout={"data": b"out"}), P.ExecSandboxEvent(stderr={"data": b"err"}),
                       P.ExecSandboxEvent(exit={"exit_code": 7})]
        result = await client.execute(payload, bound(), output_cap_bytes=6)
        assert (result.exit_code, result.stdout, result.stderr) == (7, b"out", b"err")
        assert stub.stream.cancelled
        assert await client.list_owned(bound()) == ((GEN, "lease"),)
        for operation, req, timeout in stub.calls:
            assert req.owner_id == "owner" and req.lease_id == "lease"
            assert req.workspace_scope.workspace == "dedicated"
            assert req.bound.seconds + req.bound.nanos / 1e9 == timeout
            if operation == 2:
                assert req.create.workspace_scope.workspace == "dedicated"
                assert req.create.await_main_process_attachment and not req.create.name
            if operation == "exec":
                assert req.exec.sandbox == GEN and req.exec.stdin == b"SECRET"
        assert payload.sandbox == "wrong"
    run(scenario())


def test_f4_lost_create_observes_never_recreates():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[2] = RpcFailure("UNAVAILABLE")
        with pytest.raises(ot.TransportError, match="authority_unavailable"):
            await client.create(create_request(), bound())
        stub.responses[5] = observation(admission_ready=False, create_settled=False)
        assert not (await client.status(bound())).create_settled
        with pytest.raises(ot.TransportError, match="create_not_repeatable"):
            await client.create(create_request(), bound())
        assert [c[0] for c in stub.calls] == [2, 5]
    run(scenario())


@pytest.mark.parametrize("failure", ["DEADLINE_EXCEEDED", "UNAVAILABLE", "ABORTED", "FAILED_PRECONDITION"])
def test_f7_exec_is_one_shot_on_every_rpc_failure(failure):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.events = [RpcFailure(failure)]
        with pytest.raises(ot.TransportError) as err:
            await client.execute(P.ExecSandboxRequest(stdin=b"SECRET"), bound(), output_cap_bytes=1)
        assert err.value.uncertain and "SECRET" not in str(err.value)
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=1)
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


def test_f1_kill_before_claim_and_f8_deadline_before_k2():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.responses[3] = RpcFailure("DEADLINE_EXCEEDED")
        with pytest.raises(ot.TransportError, match="sandbox_placement_operation_timeout"):
            await client.kill(bound())
        # A deadline is not evidence that the server committed the fence.
        assert not (await client.status(bound())).fenced
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=1)
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(admission_ready=False, fenced=True, destruction_observed=True,
                                        cleanup_pending=False, barrier_confirmed=True)
        await client.kill(bound())
        assert await client.list_owned(bound()) == ()
        assert [c[0] for c in stub.calls].count(3) == 2
    run(scenario())


def test_f2_claim_before_kill_remains_pending_until_barrier():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        entered, release = asyncio.Event(), asyncio.Event()
        async def held():
            entered.set()
            await release.wait()
            return P.ExecSandboxEvent(exit={"exit_code": 0})
        stub.events = [held]
        task = asyncio.create_task(client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0))
        await entered.wait()
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=False)
        stub.responses[5] = observation(admission_ready=False, fenced=True, execution_claimed=True)
        stub.responses[4] = P.ControlCancellationLeaseResponse(entries=[{"lease_id": "lease", "sandbox_ref": GEN}])
        with pytest.raises(ot.TransportError, match="sandbox_placement_operation_timeout"):
            await client.kill(bound())
        assert (await client.status(bound())).cleanup_pending
        assert await client.list_owned(bound()) == ((GEN, "lease"),)
        release.set()
        await task  # Already claimed work may complete while cancellation is pending.
        assert (await client.status(bound())).cleanup_pending
    run(scenario())


def test_f5_unseen_kill_nothing_to_settle_and_recovery_is_observation_only():
    async def scenario():
        stub = Stub()
        client = session(stub)
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": "reservation:lease"},
                                        admission_ready=False, fenced=True, cleanup_pending=False, barrier_confirmed=True)
        await client.kill(bound())
        observed = await client.status(bound())
        assert observed.create_settled and not observed.destruction_observed
        recovered = session(stub)
        with pytest.raises(ot.TransportError, match="create_not_repeatable"):
            await recovered.create(create_request(), bound())
        stub.responses[5] = observation()
        await recovered.status(bound())
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await recovered.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=1)
    run(scenario())


@pytest.mark.parametrize("changes", [
    {"lease": {"lease_id": "other", "sandbox_ref": GEN}},
    {"lease": {"lease_id": "lease", "sandbox_ref": str(uuid4())}},
    {"lease": {"lease_id": "lease", "sandbox_ref": "reservation:lease"}},
    {"barrier_confirmed": True, "cleanup_pending": False, "fenced": True, "admission_ready": False},
    {"create_settled": False},
])
def test_f9_stale_generation_wrong_lease_and_false_barrier(changes):
    async def scenario():
        stub = Stub()
        client = session(stub)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.responses[5] = observation(**changes)
        with pytest.raises(ot.TransportError):
            await client.status(bound())
    run(scenario())


@pytest.mark.parametrize("name,code", [("PERMISSION_DENIED", "owner_workspace_refused"),
                                      ("FAILED_PRECONDITION", "transition_refused"),
                                      ("ABORTED", "cas_conflict"), ("UNAVAILABLE", "authority_unavailable")])
def test_f9_owner_refusal_and_failed_inventory_never_empty(name, code):
    stub = Stub()
    stub.responses[4] = RpcFailure(name)
    with pytest.raises(ot.TransportError, match=code):
        run(session(stub).list_owned(bound()))


def test_f3_regressed_fence_after_barrier_refused():
    async def scenario():
        stub = Stub()
        client = session(stub)
        stub.responses[5] = observation(admission_ready=False, fenced=True, destruction_observed=True,
                                        cleanup_pending=False, barrier_confirmed=True)
        await client.status(bound())
        stub.responses[5] = observation()
        with pytest.raises(ot.TransportError, match="observation_regressed"):
            await client.status(bound())
    run(scenario())


def test_f8_local_deadline_cancellation_and_late_response():
    async def scenario():
        stub = Stub()
        cancelled = asyncio.Event()
        async def stall(request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        stub.responses[3] = stall
        with pytest.raises(ot.TransportError, match="sandbox_placement_operation_timeout"):
            await session(stub).kill(bound(0.01))
        await asyncio.wait_for(cancelled.wait(), 1)
        b = bound()
        b.cancelled.set()
        with pytest.raises(ot.TransportError):
            await session(stub).status(b)
        assert len(stub.calls) == 1
    run(scenario())


@pytest.mark.parametrize("events,cap,code", [([], 1, "missing_exec_exit"),
    ([P.ExecSandboxEvent(stdout={"data": b"xx"})], 1, "output_limit"),
    ([P.ExecSandboxEvent()], 1, "invalid_exec_stream"),
    ([P.ExecSandboxEvent(exit={}), P.ExecSandboxEvent(exit={})], 1, "invalid_exec_stream")])
def test_stream_faults_never_complete_or_retry(events, cap, code):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.events = events
        with pytest.raises(ot.TransportError, match=code):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=cap)
        assert stub.stream.cancelled
    run(scenario())


def test_baseline_exact_spelling_and_access_not_promoted():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        req = create_request()
        req.spec.policy.network_policies.append("model-endpoint-rule")
        paths = ot.PROXY_BASELINE_READ_ONLY + ot.PROXY_BASELINE_READ_WRITE
        req.spec.policy.filesystem.read_only.extend(paths)
        req.spec.policy.filesystem.read_only[3] = "/app/"
        with pytest.raises(ot.TransportError, match="missing_proxy_baseline"):
            await client.create(req, bound())
        assert not stub.calls
        req.spec.policy.filesystem.read_only[3] = "/app"
        stub.responses[2] = P.ControlCancellationLeaseResponse(sandbox={"metadata": {"id": GEN, "workspace": "dedicated"}})
        await client.create(req, bound())
        assert not stub.calls[0][1].create.spec.policy.filesystem.read_write
    run(scenario())


@pytest.mark.parametrize("seconds", [0, -1, True, float("nan"), float("inf")])
def test_invalid_bounds_never_dispatch(seconds):
    stub = Stub()
    with pytest.raises(ot.TransportError, match="invalid_bound"):
        run(session(stub).status(bound(seconds)))
    assert not stub.calls


def test_f6_unsupported_is_explicit_and_has_no_remote_effect():
    stub = Stub()
    client = session(stub)
    for name in ("transfer", "commit", "collect", "renew"):
        with pytest.raises(ot.UnsupportedCapability):
            getattr(client, name)()
    assert not stub.calls


def test_recovered_generation_and_wrong_workspace_refused():
    async def scenario():
        stub = Stub()
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": str(uuid4())})
        with pytest.raises(ot.TransportError, match="generation_mismatch"):
            await session(stub, expected_generation=GEN).status(bound())
        stub.responses[2] = P.ControlCancellationLeaseResponse(sandbox={"metadata": {"id": GEN, "workspace": "other"}})
        with pytest.raises(ot.TransportError, match="workspace_mismatch"):
            await session(stub, fresh=True).create(create_request(), bound())
    run(scenario())


def test_f9_authenticated_owner_model_does_not_touch_other_owner():
    async def scenario():
        stub = Stub()
        effects = []
        async def authorized(req):
            if req.owner_id != "owner":
                raise RpcFailure("PERMISSION_DENIED")
            effects.append(req.lease_id)
            return P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[3] = authorized
        spoof = ot.LeaseSession(P, stub, workspace="dedicated", owner_id="other", lease_id="other-lease")
        with pytest.raises(ot.TransportError, match="owner_workspace_refused"):
            await spoof.kill(bound())
        assert not effects
        stub.responses[5] = observation(admission_ready=False, fenced=True, destruction_observed=True,
                                        cleanup_pending=False, barrier_confirmed=True)
        await session(stub).kill(bound())
        assert effects == ["lease"]
    run(scenario())


def test_f10_import_does_not_activate_or_register_backend():
    from phase_loop_runtime import panel_invoker
    from phase_loop_runtime import sandbox_placement
    assert panel_invoker._NONLOCAL_EXECUTION_DRIVER is False
    assert not isinstance(session(Stub()), sandbox_placement.ExecutingBackend)


def test_cancellation_during_exec_cancels_stream_without_retry():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        b = bound()
        async def stall():
            b.cancelled.set()
            await asyncio.Event().wait()
        stub.events = [stall]
        with pytest.raises(ot.TransportError, match="sandbox_placement_operation_timeout"):
            await client.execute(P.ExecSandboxRequest(), b, output_cap_bytes=0)
        await asyncio.sleep(0)  # Deliver cancellation, not a wall-clock delay.
        assert stub.stream.cancelled
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
    run(scenario())


@pytest.mark.parametrize("entries", [
    [{"lease_id": "lease", "sandbox_ref": GEN}] * 2,
    [{"lease_id": "lease", "sandbox_ref": "reservation:other"}],
    [{"lease_id": "lease", "sandbox_ref": str(uuid4())}],
    [{"lease_id": "other", "sandbox_ref": GEN}],
])
def test_inventory_duplicates_malformed_and_wrong_generation_never_return_partial(entries):
    stub = Stub()
    stub.responses[4] = P.ControlCancellationLeaseResponse(entries=entries)
    with pytest.raises(ot.TransportError):
        run(session(stub, expected_generation=GEN).list_owned(bound()))


@pytest.mark.parametrize("mutation", [
    lambda r: r.spec.command.append("workload"),
    lambda r: r.spec.providers.append("credential-store"),
    lambda r: setattr(r.spec.template, "agent_socket", "/socket"),
    lambda r: setattr(r.spec, "restart_policy", 0),
    lambda r: r.spec.ClearField("policy"),
])
def test_noninert_create_refused_without_dispatch(mutation):
    stub = Stub()
    req = create_request()
    mutation(req)
    with pytest.raises(ot.TransportError, match="invalid_create"):
        run(session(stub, fresh=True).create(req, bound()))
    assert not stub.calls
