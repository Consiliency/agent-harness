"""Durable client crash boundaries, not physical server cancellation qualification."""
import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from phase_loop_runtime import openshell_journal as oj, placement_lease as journal
from phase_loop_runtime import openshell_transport as ot
import test_openshell_transport as model


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))


@pytest.fixture(params=["compact", "generated"])
def proto(request, monkeypatch):
    p = model.bindings() if request.param == "compact" else model.generated_bindings()
    monkeypatch.setattr(model, "P", p)
    return p


def opened():
    return journal.open_lease("openshell", "openshell://test.invalid/workspace")


def setup(proto, lease=None):
    lease = lease or opened()
    stub = model.Stub()
    stub.responses[2] = proto.ControlCancellationLeaseResponse(
        sandbox={"metadata": {"id": model.GEN, "workspace": "dedicated"}})
    stub.responses[5] = model.observation(lease={"lease_id": lease.lease_id, "sandbox_ref": model.GEN})
    return lease, stub, oj.JournalSession(lease, proto, stub, workspace="dedicated")


def entry(lease):
    return json.loads(lease.path.read_text())


def test_sync_before_dispatch_and_reference_before_execute(proto, monkeypatch):
    async def scenario():
        lease, stub, client = setup(proto)
        synced = []
        real = journal._fsync

        def sync(fd):
            real(fd)
            synced.append(json.loads(os.pread(fd, 65536, 0)))

        monkeypatch.setattr(journal, "_fsync", sync)
        control, execute = stub.ControlCancellationLease, stub.ExecCancellationLease

        async def checked(request, **kw):
            if request.operation == 2:
                assert synced[-1]["create_sent_at"] is not None
                assert synced[-1]["sandbox_ref"] is None
            return await control(request, **kw)

        def checked_exec(request, **kw):
            assert synced[-1]["execute_sent_at"] is not None
            assert synced[-1]["sandbox_ref"] == model.GEN
            return execute(request, **kw)

        stub.ControlCancellationLease, stub.ExecCancellationLease = checked, checked_exec
        await client.create(model.create_request(), model.bound())
        await client.status(model.bound())
        await client.execute(proto.ExecSandboxRequest(stdin=b"SECRET"), model.bound(), output_cap_bytes=0)
        assert "SECRET" not in lease.path.read_text()
        lease.abandon()
    asyncio.run(scenario())


@pytest.mark.parametrize("point", ["create_marker", "reference", "execute_marker"])
def test_sync_failure_never_dispatches_or_retries(proto, monkeypatch, point):
    async def scenario():
        lease, stub, client = setup(proto)
        if point == "execute_marker":
            await client.create(model.create_request(), model.bound())
            await client.status(model.bound())
        real = journal._fsync

        def fail(fd):
            data = json.loads(os.pread(fd, 65536, 0))
            if point != "reference" or data["sandbox_ref"] is not None:
                raise OSError("injected sync failure")
            real(fd)

        monkeypatch.setattr(journal, "_fsync", fail)
        with pytest.raises(OSError):
            if point == "execute_marker":
                await client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
            else:
                await client.create(model.create_request(), model.bound())
        assert [c[0] for c in stub.calls].count(2) == (point != "create_marker")
        assert "exec" not in [c[0] for c in stub.calls]
        with pytest.raises(ValueError):
            await client.create(model.create_request(), model.bound())
        with pytest.raises(ValueError):
            await client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
        lease.abandon()
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["opened", "create_marker", "create_reply", "reference", "execute_marker", "execute_reply"])
def test_process_crash_recovery_never_dispatches(proto, tmp_path, stage):
    # The child actually exits without abandon/unlock. Kernel flock release is the
    # recovery signal; neither timestamps nor a clean shutdown authorize dispatch.
    lease = opened()
    lease._unlock()
    pid = os.fork()
    if pid == 0:
        async def child():
            recovered = journal.recover_lease(lease.lease_id)
            # Allocate the genuinely fresh lease in this process instead.
            recovered.abandon()
            fresh, stub, client = setup(proto)
            (tmp_path / "child-id").write_text(fresh.lease_id)
            if stage == "opened":
                os._exit(0)
            if stage == "create_marker":
                fresh.mark_dispatch(client, "create")
                os._exit(0)
            if stage == "create_reply":
                fresh.record_transport_ref = lambda *_: os._exit(0)
            await client.create(model.create_request(), model.bound())
            if stage == "reference":
                os._exit(0)
            await client.status(model.bound())
            if stage == "execute_marker":
                fresh.mark_dispatch(client, "execute")
                os._exit(0)
            await client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
            os._exit(0)
        try:
            asyncio.run(child())
        except BaseException:
            os._exit(2)
    assert os.waitpid(pid, 0)[1] == 0
    recovered = journal.recover_lease((tmp_path / "child-id").read_text())
    async def check():
        _, stub, client = setup(proto, recovered)
        for call in (client.create(model.create_request(), model.bound()),
                     client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)):
            with pytest.raises(ValueError, match="dispatch forbidden"):
                await call
        assert stub.calls == []
        await client.status(model.bound())
        assert entry(recovered)["sandbox_ref"] == model.GEN
    try:
        asyncio.run(check())
    finally:
        recovered.abandon()


def test_exclusive_attachment_and_process_lock(proto):
    lease, _, _ = setup(proto)
    with pytest.raises(ValueError):
        setup(proto, lease)
    with pytest.raises(BlockingIOError):
        journal.recover_lease(lease.lease_id)
    code = """
import sys
from phase_loop_runtime.placement_lease import recover_lease
try:
    recover_lease(sys.argv[1])
except BlockingIOError:
    sys.exit(0)
sys.exit(2)
"""
    result = subprocess.run([sys.executable, "-c", code, lease.lease_id],
                            env={**os.environ, "PYTHONPATH": str(Path(journal.__file__).parents[1])})
    assert result.returncode == 0
    lease.abandon()


@pytest.mark.parametrize("poison", ["status", "list"])
def test_poison_never_restores_execute_and_kill_remains_available(proto, poison):
    async def scenario():
        lease, stub, client = setup(proto)
        await client.create(model.create_request(), model.bound())
        await client.status(model.bound())
        if poison == "status":
            stub.responses[5] = model.RpcFailure("UNAVAILABLE")
            with pytest.raises(ot.TransportError):
                await client.status(model.bound())
        else:
            stub.responses[4] = proto.ControlCancellationLeaseResponse(entries=[{
                "lease_id": lease.lease_id, "sandbox_ref": "11111111-1111-4111-8111-111111111111"}])
            with pytest.raises(ot.TransportError):
                await client.list_owned(model.bound())
        stub.responses[5] = model.observation(lease={"lease_id": lease.lease_id, "sandbox_ref": model.GEN})
        await client.status(model.bound())
        with pytest.raises(ot.TransportError):
            await client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
        assert "exec" not in [c[0] for c in stub.calls]
        stub.responses[3] = proto.ControlCancellationLeaseResponse(barrier_confirmed=True)
        stub.responses[5] = model.observation(
            lease={"lease_id": lease.lease_id, "sandbox_ref": model.GEN}, admission_ready=False,
            fenced=True, destruction_observed=True, cleanup_pending=False, barrier_confirmed=True)
        await client.kill(model.bound())
        assert entry(lease)["confirmed_killed_at"] is not None
        other = opened()
        assert other.lease_id != lease.lease_id
        other.abandon()
        lease.abandon()
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["clean", "pending", "listed", "list_failure", "wrong_generation", "false_status",
                                  "timeout", "malformed_list", "wrong_owner"])
def test_existing_reaper_requires_barrier_status_and_complete_absence(proto, case):
    lease, stub, _ = setup(proto)
    lease.record_sandbox_ref(model.GEN)
    lease.abandon()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    try:
        stub.responses[3] = (model.RpcFailure("DEADLINE_EXCEEDED") if case == "timeout" else
                             proto.ControlCancellationLeaseResponse(barrier_confirmed=case != "pending"))
        stub.responses[5] = model.observation(
            lease={"lease_id": lease.lease_id, "sandbox_ref": model.GEN if case != "wrong_generation"
                   else "11111111-1111-4111-8111-111111111111"}, admission_ready=False,
            fenced=True, destruction_observed=True, cleanup_pending=case == "false_status",
            barrier_confirmed=case != "false_status")
        stub.responses[4] = (model.RpcFailure("UNAVAILABLE") if case == "list_failure" else
                             proto.ControlCancellationLeaseResponse(entries=[{
                                 "lease_id": lease.lease_id, "sandbox_ref": model.GEN}]
                                 if case == "listed" else []))
        if case == "malformed_list":
            stub.responses[4] = proto.ControlCancellationLeaseResponse(entries=[{"lease_id": "unknown", "sandbox_ref": "bad"}])
        adapter = oj.ReaperAdapter(proto, stub, loop=loop, workspace="dedicated",
                                   owner_id="wrong" if case == "wrong_owner" else lease.owner_id)
        outcome = journal.reap(lambda _: adapter, model.bound())
        assert outcome == {"cleared": (lease.lease_id,) if case == "clean" else (),
                           "kept": () if case == "clean" else (lease.lease_id,)}
        assert lease.path.exists() == (case != "clean")
        if case == "wrong_owner":
            assert stub.calls == []
        if case != "clean":
            assert entry(lease)["abandoned"]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


@pytest.mark.parametrize("change", [{"future_obligation": True}, {"create_sent_at": "bad"},
                                    {"lease_id": "other"}, {"abandoned": "false"}])
def test_malformed_unknown_obligations_are_retained(change):
    lease = opened()
    lease.abandon()
    data = entry(lease)
    data.update(change)
    lease.path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        journal.recover_lease(lease.lease_id)
    def forbidden(_):
        pytest.fail("malformed entry contacted backend")
    assert journal.reap(forbidden, model.bound()) == {"cleared": (), "kept": (lease.lease_id,)}
    assert entry(lease) == data


def test_legacy_without_markers_recovers_observation_only(proto):
    lease = opened()
    lease.abandon()
    data = entry(lease)
    del data["create_sent_at"], data["execute_sent_at"]
    lease.path.write_text(json.dumps(data))
    recovered = journal.recover_lease(lease.lease_id)
    _, stub, client = setup(proto, recovered)
    with pytest.raises(ValueError):
        asyncio.run(client.create(model.create_request(), model.bound()))
    assert stub.calls == []
    recovered.abandon()


def test_concurrent_creates_have_one_durable_dispatch(proto):
    async def scenario():
        lease, stub, client = setup(proto)
        results = await asyncio.gather(
            client.create(model.create_request(), model.bound()),
            client.create(model.create_request(), model.bound()), return_exceptions=True)
        assert sum(isinstance(result, ValueError) for result in results) == 1
        assert [c[0] for c in stub.calls] == [2]
        assert entry(lease)["create_sent_at"] is not None
        lease.abandon()
    asyncio.run(scenario())


def test_inherited_handle_cannot_dispatch(proto):
    lease, stub, client = setup(proto)
    pid = os.fork()
    if pid == 0:
        try:
            asyncio.run(client.create(model.create_request(), model.bound()))
        except ValueError:
            os._exit(0)
        os._exit(2)
    assert os.waitpid(pid, 0)[1] == 0
    assert entry(lease)["create_sent_at"] is None and stub.calls == []
    lease.abandon()


def test_pending_kill_abandons_with_honest_notice(proto):
    from phase_loop_runtime import seat_jail
    async def scenario():
        lease, stub, client = setup(proto)
        stub.responses[3] = proto.ControlCancellationLeaseResponse(barrier_confirmed=False)
        with pytest.raises(ot.TransportError, match="operation_timeout"):
            await client.kill(model.bound())
        assert not lease.held and entry(lease)["abandoned"]
        assert entry(lease)["confirmed_killed_at"] is None
        notice = seat_jail.render_notice("sandbox_placement_release_unconfirmed", "test")
        assert "may have started or still be running" in notice.fix
        assert "lease is kept for the reaper" in notice.fix
    asyncio.run(scenario())


def test_short_write_blocks_dispatch_and_retains_obligation(proto, monkeypatch):
    async def scenario():
        lease, stub, client = setup(proto)
        real = os.pwrite
        def short(fd, data, offset):
            return real(fd, data[:8], offset)
        monkeypatch.setattr(os, "pwrite", short)
        with pytest.raises(OSError, match="short placement journal write"):
            await client.create(model.create_request(), model.bound())
        assert stub.calls == [] and lease.fenced
        lease.abandon()
        assert lease.path.exists()
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["create", "execute"])
def test_uncertain_dispatch_is_never_repeated(proto, operation):
    async def scenario():
        lease, stub, client = setup(proto)
        if operation == "create":
            stub.responses[2] = model.RpcFailure("UNAVAILABLE")
        else:
            await client.create(model.create_request(), model.bound())
            await client.status(model.bound())
            stub.events = [model.RpcFailure("UNAVAILABLE")]
        with pytest.raises(ot.TransportError):
            if operation == "create":
                await client.create(model.create_request(), model.bound())
            else:
                await client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
        await client.status(model.bound())
        for call in (client.create(model.create_request(), model.bound()),
                     client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)):
            with pytest.raises(ValueError):
                await call
        assert [c[0] for c in stub.calls].count(2) == 1
        assert [c[0] for c in stub.calls].count("exec") == (operation == "execute")
        lease.abandon()
    asyncio.run(scenario())
