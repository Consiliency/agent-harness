"""Modeled client falsifiers, NOT physical OpenShell conformance.

The compact protobuf descriptor retains the private envelope field numbers.
Public nested messages are test doubles, not a generated public API; deployment must supply full
generated bindings from the reviewed server revision, not this test fixture.
"""

import asyncio
import importlib
import os
import sys
from types import SimpleNamespace
import threading
from uuid import uuid4

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf import duration_pb2, struct_pb2
import pytest

from phase_loop_runtime import openshell_transport as ot
from phase_loop_runtime.sandbox_placement import OperationBound


def bindings():
    file = descriptor_pb2.FileDescriptorProto(name="private_fixture.proto", package="openshell.v1", syntax="proto3")
    file.dependency.extend(["google/protobuf/duration.proto", "google/protobuf/struct.proto"])
    # name, field number, scalar type/message name, repeated
    schemas = {
        "Workspace": [("workspace", 1, "string", False)],
        "Meta": [("id", 1, "string", False), ("workspace", 7, "string", False)],
        "Filesystem": [("read_only", 2, "string", True), ("read_write", 3, "string", True)],
        "Policy": [("filesystem", 2, "Filesystem", False), ("network_policies", 5, "NetworkPoliciesEntry", True)],
        "NetworkPolicyRule": [("name", 1, "string", False)],
        "NetworkPoliciesEntry": [("key", 1, "string", False), ("value", 2, "NetworkPolicyRule", False)],
        "EnvironmentEntry": [("key", 1, "string", False), ("value", 2, "string", False)],
        "ServiceExposure": [("service", 1, "string", False), ("target_port", 2, "uint32", False)],
        "Template": [("agent_socket", 3, "string", False), ("environment", 6, "EnvironmentEntry", True),
                     ("driver_config", 11, "Struct", False)],
        "Spec": [("environment", 5, "EnvironmentEntry", True), ("template", 6, "Template", False),
                 ("policy", 7, "Policy", False), ("providers", 8, "string", True),
                 ("command", 12, "string", True), ("restart_policy", 15, "int32", False)],
        "Sandbox": [("metadata", 1, "Meta", False), ("spec", 2, "Spec", False)],
        "CreateSandboxRequest": [("spec", 1, "Spec", False), ("name", 2, "string", False),
                                 ("await_main_process_attachment", 5, "bool", False),
                                 ("workload_template", 6, "string", False),
                                 ("workspace_scope", 7, "Workspace", False),
                                 ("request_id", 8, "string", False), ("service_exposures", 9, "ServiceExposure", True)],
        "ExecSandboxRequest": [("sandbox", 1, "string", False), ("command", 2, "string", True),
                               ("workdir", 3, "string", False), ("environment", 4, "EnvironmentEntry", True),
                               ("execution_timeout", 105, "Duration", False), ("no_login_shell", 10, "bool", False),
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
    types = {"string": 9, "bytes": 12, "bool": 8, "int32": 5, "uint32": 13}
    for name, fields in schemas.items():
        msg = file.message_type.add(name=name)
        if name in ("NetworkPoliciesEntry", "EnvironmentEntry"):
            msg.options.map_entry = True
        if name == "ExecSandboxEvent":
            msg.oneof_decl.add(name="payload")
        for key, number, kind, repeated in fields:
            f = msg.field.add(name=key, number=number, label=3 if repeated else 1,
                              type=types.get(kind, 11))
            if kind not in types:
                f.type_name = f".google.protobuf.{kind}" if kind in ("Duration", "Struct") else f".openshell.v1.{kind}"
            if name == "ExecSandboxEvent":
                f.oneof_index = 0
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(duration_pb2.DESCRIPTOR.serialized_pb)
    pool.AddSerializedFile(struct_pb2.DESCRIPTOR.serialized_pb)
    pool.Add(file)
    return SimpleNamespace(**{name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"openshell.v1.{name}"))
                              for name in schemas})


P = bindings()


def generated_bindings():
    path = os.environ.get("OPENSHELL_GENERATED_DIR")
    if not path and os.environ.get("OPENSHELL_SDK_QUALIFICATION") == "1":
        pytest.fail("qualification requires OPENSHELL_GENERATED_DIR")
    if not path:
        pytest.skip("generated SDK qualification requires OPENSHELL_GENERATED_DIR; see transport doc")
    # An explicitly requested SDK must import successfully, never silently skip.
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module("openshell_pb2")


@pytest.fixture(params=["compact", "generated"], autouse=True)
def transport_bindings(request, monkeypatch):
    proto = bindings() if request.param == "compact" else generated_bindings()
    monkeypatch.setattr(sys.modules[__name__], "P", proto)
    return proto

# Fixed values: pytest-xdist requires identical parametrize IDs in every worker.
GEN = "d1e50366-0a54-4df0-b778-45b37b391df6"
OTHER_GEN = "b971370c-a1b8-432a-a987-cef35cbc474b"


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
        # The server may still run claimed work, but local cancellation refuses it.
        with pytest.raises(ot.TransportError, match="operation_timeout"):
            await task
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
    {"lease": {"lease_id": "lease", "sandbox_ref": OTHER_GEN}},
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
    ([{"stdout": {"data": b"xx"}}], 1, "output_limit"),
    ([{}], 1, "invalid_exec_stream"),
    ([{"exit": {}}, {"exit": {}}], 1, "invalid_exec_stream")])
def test_stream_faults_never_complete_or_retry(events, cap, code):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.events = [P.ExecSandboxEvent(**event) for event in events]
        with pytest.raises(ot.TransportError, match=code):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=cap)
        assert stub.stream.cancelled
    run(scenario())


def test_baseline_exact_spelling_and_access_not_promoted():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        req = create_request()
        req.spec.policy.network_policies["model-endpoint-rule"].name = "model-endpoint-rule"
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


@pytest.mark.parametrize("seconds", [0, -1, True, float("nan"), float("inf"), "1", None, 1j, 10**400])
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
    [{"lease_id": "lease", "sandbox_ref": OTHER_GEN}],
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


@pytest.mark.parametrize("changes,code", [
    ({"lease": {"lease_id": "lease", "sandbox_ref": OTHER_GEN}}, "generation_mismatch"),
    ({"fenced": True}, "invalid_observation"),
    ({"lease": {"lease_id": "other", "sandbox_ref": GEN}}, "lease_mismatch"),
])
def test_r10_rejected_status_permanently_prevents_exec_but_allows_recovery(changes, code):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.responses[5] = observation(**changes)
        with pytest.raises(ot.TransportError, match=code):
            await client.status(bound())
        if changes.get("fenced"):
            assert client._kill_requested
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        stub.responses[5] = observation()
        await client.status(bound())
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(admission_ready=False, fenced=True, destruction_observed=True,
                                        cleanup_pending=False, barrier_confirmed=True)
        await client.kill(bound())
        assert not any(call[0] == "exec" for call in stub.calls)
    run(scenario())


def test_r10_invalid_status_does_not_bind_identity():
    async def scenario():
        stub = Stub()
        client = session(stub)
        stub.responses[5] = observation(create_settled=False)
        with pytest.raises(ot.TransportError, match="invalid_observation"):
            await client.status(bound())
        assert client._generation is None
        other = str(uuid4())
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": other})
        assert (await client.status(bound())).sandbox_ref == other
    run(scenario())


@pytest.mark.parametrize("reference", [GEN, "reservation:lease"])
def test_r10_invalid_inventory_does_not_bind_identity(reference):
    async def scenario():
        stub = Stub()
        client = session(stub)
        stub.responses[4] = P.ControlCancellationLeaseResponse(entries=[
            {"lease_id": "lease", "sandbox_ref": reference},
            {"lease_id": "other", "sandbox_ref": "bad"}])
        with pytest.raises(ot.TransportError, match="invalid_inventory"):
            await client.list_owned(bound())
        assert client._generation is None
        other = str(uuid4())
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": other})
        assert (await client.status(bound())).sandbox_ref == other
    run(scenario())


@pytest.mark.parametrize("source", ["status", "list_owned"])
@pytest.mark.parametrize("destination", ["status", "list_owned", "create"])
def test_reservation_cannot_transition_to_uuid(source, destination):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": "reservation:lease"},
                                        admission_ready=False, fenced=True,
                                        cleanup_pending=False, barrier_confirmed=True)
        stub.responses[4] = P.ControlCancellationLeaseResponse(entries=[
            {"lease_id": "lease", "sandbox_ref": "reservation:lease"}])
        await getattr(client, source)(bound())
        stub.responses[5] = observation(admission_ready=False, fenced=True,
                                        destruction_observed=True, cleanup_pending=False, barrier_confirmed=True)
        stub.responses[4] = P.ControlCancellationLeaseResponse(entries=[
            {"lease_id": "lease", "sandbox_ref": GEN}])
        stub.responses[2] = P.ControlCancellationLeaseResponse(
            sandbox={"metadata": {"id": GEN, "workspace": "dedicated"}})
        with pytest.raises(ot.TransportError):
            if destination == "create":
                await client.create(create_request(), bound())
            else:
                await getattr(client, destination)(bound())
        assert client._generation is None
    run(scenario())


def test_r10_create_settled_cannot_regress():
    async def scenario():
        stub = Stub()
        client = session(stub)
        stub.responses[5] = observation(admission_ready=False)
        await client.status(bound())
        stub.responses[5] = observation(admission_ready=False, create_settled=False)
        with pytest.raises(ot.TransportError, match="observation_regressed"):
            await client.status(bound())
    run(scenario())


@pytest.mark.parametrize("mode", ["noncallable", "raises", "property", "unhashable"])
def test_r10_remote_error_mapping_is_total_and_sanitized(mode):
    import traceback

    class WrapperFailure(Exception):
        @property
        def code(self):
            if mode == "property":
                raise ValueError("SECRET property")
            if mode == "noncallable":
                return 503
            def code():
                if mode == "raises":
                    raise ValueError("SECRET code")
                return SimpleNamespace(name=[])
            return code

    stub = Stub()
    stub.responses[5] = WrapperFailure("SECRET remote prose")
    with pytest.raises(ot.TransportError, match="authority_unavailable") as err:
        run(session(stub).status(bound()))
    assert err.value.uncertain
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert "SECRET" not in "".join(traceback.format_exception(err.value))


def test_r10_outer_cancellation_cancels_create_without_replay():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def stall(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        stub.responses[2] = stall
        task = asyncio.create_task(client.create(create_request(), bound()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 1)
        with pytest.raises(ot.TransportError, match="create_not_repeatable"):
            await client.create(create_request(), bound())
        assert [call[0] for call in stub.calls] == [2]
    run(scenario())


def test_r10_kill_status_shares_remaining_bound():
    async def scenario():
        stub = Stub()
        async def slow(request):
            await asyncio.sleep(0.02)
            return P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[3] = slow
        stub.responses[5] = observation(admission_ready=False, fenced=True, destruction_observed=True,
                                        cleanup_pending=False, barrier_confirmed=True)
        await session(stub).kill(bound())
        kill, status = stub.calls
        assert status[2] <= kill[2] - 0.02
        assert status[1].bound.seconds + status[1].bound.nanos / 1e9 == pytest.approx(status[2])
    run(scenario())


def test_status_rpc_refusal_also_permanently_prevents_exec():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.responses[5] = RpcFailure("FAILED_PRECONDITION")
        with pytest.raises(ot.TransportError, match="transition_refused"):
            await client.status(bound())
        stub.responses[5] = observation()
        await client.status(bound())
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        assert not any(call[0] == "exec" for call in stub.calls)
    run(scenario())


def created_response():
    return P.ControlCancellationLeaseResponse(sandbox={"metadata": {"id": GEN, "workspace": "dedicated"}})
BARRIER = dict(admission_ready=False, fenced=True, destruction_observed=True, cleanup_pending=False, barrier_confirmed=True)


def test_pass_honest_progression_not_ready_then_ready_still_executes():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[5] = observation(admission_ready=False)
        await c.status(bound())
        stub.responses[5] = observation()
        await c.status(bound())
        assert (await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)).exit_code == 0
        assert [x[0] for x in stub.calls] == [2, 5, 5, "exec"]
    run(s())


@pytest.mark.parametrize("failure", ["UNAVAILABLE", "DEADLINE_EXCEEDED", "local_deadline", "invalid_bound", "precancelled"])
def test_limit_any_status_failure_poisons_exec_liveness_cost(failure):
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[5] = observation()
        await c.status(bound())
        b = bound()
        if failure in ("UNAVAILABLE", "DEADLINE_EXCEEDED"):
            stub.responses[5] = RpcFailure(failure)
        elif failure == "local_deadline":
            async def slow(req):
                await asyncio.Event().wait()
            stub.responses[5] = slow
            b = bound(0.05)
        elif failure == "invalid_bound":
            b = bound(0)
        else:
            b.cancelled.set()
        with pytest.raises(ot.TransportError):
            await c.status(b)
        stub.responses[5] = observation()
        await c.status(bound())
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        # honest cleanup still available
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(**BARRIER)
        await c.kill(bound())
        assert not any(x[0] == "exec" for x in stub.calls)
    run(s())


def test_limit_status_before_create_on_fresh_lease_poisons_exec():
    # Pinned server: STATUS on an unreserved lease -> Error::Refused -> FAILED_PRECONDITION.
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[5] = RpcFailure("FAILED_PRECONDITION")
        with pytest.raises(ot.TransportError, match="transition_refused"):
            await c.status(bound())
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[5] = observation()
        await c.status(bound())
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
    run(s())


def test_pass_outer_cancellation_of_status_propagates_and_is_not_poison():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[5] = observation()
        await c.status(bound())
        entered = asyncio.Event()
        async def stall(req):
            entered.set()
            await asyncio.Event().wait()
        stub.responses[5] = stall
        t = asyncio.create_task(c.status(bound()))
        await entered.wait()
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        assert not c._poisoned
        # Asymmetry: unlike a deadline, outer cancellation leaves prior ready obs usable.
        assert (await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)).exit_code == 0
    run(s())


def test_pass_kill_before_create_reservation_barrier_and_create_refused():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": "reservation:lease"},
                                        admission_ready=False, fenced=True, cleanup_pending=False,
                                        barrier_confirmed=True)
        await c.kill(bound())
        with pytest.raises(ot.TransportError, match="create_not_repeatable"):
            await c.create(create_request(), bound())
        assert [x[0] for x in stub.calls] == [3, 5]
    run(s())


def test_pass_concurrent_status_out_of_order_regression_poisons():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        gate, entered = asyncio.Event(), asyncio.Event()
        async def first(req):
            entered.set()
            await gate.wait()
            return observation()  # older, ready
        stub.responses[5] = first
        t1 = asyncio.create_task(c.status(bound()))
        await entered.wait()
        stub.responses[5] = observation(admission_ready=False, fenced=True)  # newer, fenced
        await c.status(bound())
        gate.set()
        with pytest.raises(ot.TransportError, match="observation_regressed"):
            await t1
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
    run(s())


def test_r12_list_generation_mismatch_permanently_poisons_exec():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[5] = observation()
        await c.status(bound())
        other = "00000000-0000-4000-8000-000000000001"
        stub.responses[4] = P.ControlCancellationLeaseResponse(entries=[{"lease_id": "lease", "sandbox_ref": other}])
        with pytest.raises(ot.TransportError, match="generation_mismatch"):
            await c.list_owned(bound())
        assert c._generation == GEN
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        stub.responses[5] = observation()
        await c.status(bound())
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(**BARRIER)
        await c.kill(bound())
        assert not any(x[0] == "exec" for x in stub.calls)
    run(s())


def test_limit_impossible_uuid_to_reservation_wedges_kill_fail_closed():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[3] = P.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = observation(lease={"lease_id": "lease", "sandbox_ref": "reservation:lease"},
                                        admission_ready=False, fenced=True, cleanup_pending=False,
                                        barrier_confirmed=True)
        with pytest.raises(ot.TransportError, match="invalid_generation"):
            await c.kill(bound())
        assert c._kill_requested and c._poisoned
    run(s())


def test_limit_context_object_retained_but_suppressed():
    import traceback

    stub = Stub()
    stub.responses[5] = RpcFailure("UNAVAILABLE")
    with pytest.raises(ot.TransportError) as e:
        run(session(stub).status(bound()))
    assert e.value.__suppress_context__ and e.value.__cause__ is None
    assert e.value.__context__ is not None  # raw object reachable programmatically
    assert "SECRET" not in "".join(traceback.format_exception(e.value))


def test_pass_rejected_fenced_mismatch_sets_local_kill_and_blocks_create():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[5] = observation(lease={"lease_id": "other", "sandbox_ref": GEN}, fenced=True, admission_ready=False)
        with pytest.raises(ot.TransportError, match="lease_mismatch"):
            await c.status(bound())
        with pytest.raises(ot.TransportError, match="create_not_repeatable"):
            await c.create(create_request(), bound())
        assert [x[0] for x in stub.calls] == [5]
    run(s())


def test_pass_cancel_during_exec_propagates_one_shot():
    async def s():
        stub = Stub()
        c = session(stub, fresh=True)
        stub.responses[2] = created_response()
        await c.create(create_request(), bound())
        stub.responses[5] = observation()
        await c.status(bound())
        entered = asyncio.Event()
        async def hang():
            entered.set()
            await asyncio.Event().wait()
        stub.events = [hang]
        t = asyncio.create_task(c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0))
        await entered.wait()
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        await asyncio.sleep(0)
        assert stub.stream.cancelled
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await c.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
    run(s())


def test_split_dispatch_delayed_output_and_terminal_eof():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        release, eof = asyncio.Event(), asyncio.Event()

        async def delayed():
            await release.wait()
            return P.ExecSandboxEvent(exit={"exit_code": 0})

        async def delayed_eof():
            await eof.wait()
            raise StopAsyncIteration

        stub.events = [delayed, delayed_eof]
        handle = await client.dispatch(P.ExecSandboxRequest(), bound(.02), stream_bound=bound(1),
                                       output_cap_bytes=0, message_cap=1)
        assert await handle.wait(.04) is None  # past dispatch budget, no first event
        release.set()
        assert await handle.wait(.01) is None  # terminal exit alone is insufficient
        eof.set()
        assert (await handle.wait(.5)).exit_code == 0
        assert (await handle.wait(0)).exit_code == 0
        calls = [c for c in stub.calls if c[0] == "exec"]
        assert len(calls) == 1
        assert calls[0][1].bound.nanos == 20_000_000 and calls[0][2] == 1
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=bound(),
                                  output_cap_bytes=0, message_cap=1)
    run(scenario())


@pytest.mark.parametrize("stop", ["bound", "cancel", "outer", "deadline"])
def test_split_stream_stop_wins_terminal_race(stop):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        lifetime = bound(.04 if stop == "deadline" else 1)
        release = asyncio.Event()

        async def terminal():
            await release.wait()
            if stop == "bound":
                lifetime.cancelled.set()
            return P.ExecSandboxEvent(exit={})

        stub.events = [terminal]
        handle = await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=lifetime,
                                       output_cap_bytes=0, message_cap=1)
        if stop == "cancel":
            handle.cancel()
        elif stop == "outer":
            task = asyncio.create_task(handle.wait(1))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif stop == "deadline":
            await asyncio.sleep(.06)
        release.set()
        with pytest.raises(ot.TransportError, match="operation_timeout"):
            await handle.wait(.2)
        assert stub.stream.cancelled
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


@pytest.mark.parametrize("events,byte_cap,msg_cap,code", [
    ([{"stdout": {"data": b"xx"}}], 1, 2, "output_limit"),
    ([{"stdout": {}}, {"stdout": {}}], 0, 1, "message_limit"),
    ([], 0, 1, "missing_exec_exit"),
    ([{"exit": {}}, {"stdout": {}}], 1, 3, "invalid_exec_stream"),
    (["lost"], 0, 1, "authority_unavailable"),
])
def test_split_stream_fault_is_sticky_without_redispatch(events, byte_cap, msg_cap, code):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.events = [RpcFailure("UNAVAILABLE") if e == "lost" else P.ExecSandboxEvent(**e) for e in events]
        handle = await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=bound(),
                                       output_cap_bytes=byte_cap, message_cap=msg_cap)
        for _ in range(2):
            with pytest.raises(ot.TransportError, match=code) as error:
                await handle.wait(.2)
            assert error.value.uncertain
        assert stub.stream.cancelled
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


def test_split_dispatch_cancel_races_created_call():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        dispatch_bound = bound()
        real = stub.ExecCancellationLease

        def cancelled(*args, **kwargs):
            stream = real(*args, **kwargs)
            dispatch_bound.cancelled.set()
            return stream

        stub.ExecCancellationLease = cancelled
        with pytest.raises(ot.TransportError, match="operation_timeout"):
            await client.dispatch(P.ExecSandboxRequest(), dispatch_bound, stream_bound=bound(),
                                  output_cap_bytes=0, message_cap=1)
        assert stub.stream.cancelled
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_split_completed_result_cannot_escape_later_stop(stop):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        lifetime = bound(.04 if stop == "deadline" else 1)
        handle = await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=lifetime,
                                       output_cap_bytes=0, message_cap=1)
        assert (await handle.wait(.02)).exit_code == 0
        if stop == "cancel":
            lifetime.cancelled.set()
        else:
            await asyncio.sleep(.05)
        with pytest.raises(ot.TransportError, match="operation_timeout"):
            await handle.wait(0)
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


@pytest.mark.parametrize("lifetime,messages", [(None, 1), (float("inf"), 1), (0, 1), (1, 0), (1, True)])
def test_split_invalid_limits_never_dispatch(lifetime, messages):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        with pytest.raises(ot.TransportError):
            await client.dispatch(P.ExecSandboxRequest(), bound(),
                                  stream_bound=None if lifetime is None else bound(lifetime),
                                  output_cap_bytes=0, message_cap=messages)
        assert "exec" not in [c[0] for c in stub.calls]
    run(scenario())


def stall_execute_poll(monkeypatch):
    """Advance the clock between wait's successful check and remaining-time read."""
    original_wait = ot.ExecStream.wait

    async def wait(handle, wait_s):
        loop = asyncio.get_running_loop()
        original_check = handle._check
        with monkeypatch.context() as patch:
            def check():
                original_check()
                patch.setattr(loop, "time", lambda: handle._end + wait_s + 1)
            patch.setattr(handle, "_check", check)
            result = await original_wait(handle, wait_s)
            assert result is None
            return result

    monkeypatch.setattr(ot.ExecStream, "wait", wait)


def test_execute_poll_expiry_cancels_and_refuses(monkeypatch):
    stall_execute_poll(monkeypatch)

    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        with pytest.raises(ot.TransportError, match="operation_timeout") as error:
            await client.execute(P.ExecSandboxRequest(), bound(), output_cap_bytes=0)
        assert error.value.uncertain
        assert stub.stream.cancelled
        with pytest.raises(asyncio.CancelledError):
            await client._exec_stream._task
        with pytest.raises(ot.TransportError, match="execute_not_permitted"):
            await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=bound(),
                                  output_cap_bytes=0, message_cap=1)
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


@pytest.mark.parametrize("message_cap", [1, 2])
def test_split_message_cap_counts_exit(message_cap):
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        stub.events = [P.ExecSandboxEvent(stdout={}), P.ExecSandboxEvent(exit={})]
        handle = await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=bound(),
                                       output_cap_bytes=0, message_cap=message_cap)
        if message_cap == 1:
            with pytest.raises(ot.TransportError, match="message_limit") as error:
                await handle.wait(.2)
            assert error.value.uncertain
        else:
            assert (await handle.wait(.2)).exit_code == 0
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())


def test_split_live_kill_stops_collector():
    async def scenario():
        stub = Stub()
        client = session(stub, fresh=True)
        stub.responses[5] = observation()
        await client.status(bound())
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def pending():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        stub.events = [pending]
        handle = await client.dispatch(P.ExecSandboxRequest(), bound(), stream_bound=bound(30),
                                       output_cap_bytes=0, message_cap=1)
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(ot.TransportError, match="operation_timeout"):
            await client.kill(bound())  # pending barrier still stops local collection
        # Check before wait(), whose refusal would otherwise cancel the collector.
        assert stub.stream.cancelled
        await asyncio.wait_for(stopped.wait(), 1)
        with pytest.raises(asyncio.CancelledError):
            await handle._task
        assert [c[0] for c in stub.calls].count("exec") == 1
    run(scenario())
