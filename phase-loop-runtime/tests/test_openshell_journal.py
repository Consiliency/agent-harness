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
@pytest.mark.parametrize("backend_class", [oj.ReaperAdapter, oj.OpenShellBackend])
def test_existing_reaper_requires_barrier_status_and_complete_absence(proto, case, backend_class):
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
        adapter = backend_class(proto, stub, loop=loop, workspace="dedicated",
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


@pytest.fixture
def running_loop():
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    loop.call_soon(ready.set)
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    assert ready.wait(2)
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(2)
        assert not thread.is_alive()
        loop.close()


def cleanup_backend(proto, loop, case="clean"):
    lease, stub, client = setup(proto)
    lease.record_transport_ref(client, model.GEN)
    lease.abandon()
    stub.responses[3] = proto.ControlCancellationLeaseResponse(barrier_confirmed=case != "pending")
    stub.responses[5] = model.observation(
        lease={"lease_id": "wrong" if case == "identity" else lease.lease_id,
               "sandbox_ref": "11111111-1111-4111-8111-111111111111"
               if case == "generation" else model.GEN},
        admission_ready=False, fenced=True, destruction_observed=True,
        cleanup_pending=False, barrier_confirmed=True)
    stub.responses[4] = proto.ControlCancellationLeaseResponse()
    backend = oj.OpenShellBackend(proto, stub, loop=loop, workspace="dedicated",
                                  owner_id=lease.owner_id)
    return lease, stub, backend


@pytest.mark.parametrize("case", ["clean", "pending", "identity", "generation"])
def test_cleanup_backend_kill_retains_until_reap(proto, running_loop, case):
    lease, stub, backend = cleanup_backend(proto, running_loop, case)
    if case == "clean":
        backend.kill(lease.lease_id, model.bound())
        assert entry(lease)["confirmed_killed_at"] is not None
    else:
        with pytest.raises(oj.PlacementUnavailable):
            backend.kill(lease.lease_id, model.bound())
        assert entry(lease)["confirmed_killed_at"] is None
    assert lease.path.exists()
    assert entry(lease)["sandbox_ref"] == model.GEN
    assert entry(lease)["abandoned"]
    result = journal.reap(lambda _: backend, model.bound())
    assert result["cleared"] == ((lease.lease_id,) if case == "clean" else ())
    assert all(call[0] in (3, 4, 5) for call in stub.calls)
    from phase_loop_runtime.sandbox_placement import ExecutingBackend
    assert not isinstance(backend, ExecutingBackend)
    assert not hasattr(backend, "execute")


def test_cleanup_backend_exclusive_lock(proto, running_loop):
    lease, stub, backend = cleanup_backend(proto, running_loop)
    recovered = journal.recover_lease(lease.lease_id)
    try:
        with pytest.raises(BlockingIOError):
            backend.kill(lease.lease_id, model.bound())
        assert journal.reap(lambda _: backend, model.bound())["cleared"] == ()
        assert stub.calls == []
    finally:
        recovered.abandon()


@pytest.mark.parametrize("operation", ["kill", "list", "reap"])
def test_bridge_rejects_loop_thread_before_wait(proto, operation):
    async def scenario():
        lease, stub, backend = cleanup_backend(proto, asyncio.get_running_loop())
        with pytest.raises(ValueError, match="external thread"):
            if operation == "kill":
                backend.kill(lease.lease_id, model.bound())
            elif operation == "list":
                backend.list_owned(lease.owner_id, model.bound())
            else:
                journal.reap(lambda _: backend, model.bound())
        assert stub.calls == []
        recovered = journal.recover_lease(lease.lease_id)
        recovered.abandon()
    asyncio.run(scenario())


@pytest.mark.parametrize("closed", [False, True])
def test_bridge_rejects_stopped_loop(proto, closed):
    loop = asyncio.new_event_loop()
    if closed:
        loop.close()
    try:
        lease, stub, backend = cleanup_backend(proto, loop)
        with pytest.raises(ValueError, match="running loop"):
            backend.list_owned(lease.owner_id, model.bound())
        assert stub.calls == []
    finally:
        loop.close()


@pytest.mark.parametrize("operation", ["kill", "reap"])
def test_late_cleanup_completion_cannot_write_recovered_journal(proto, running_loop, monkeypatch, operation):
    lease, _, backend = cleanup_backend(proto, running_loop)
    entered, finished = threading.Event(), threading.Event()
    release = asyncio.Event()

    class LateSession:
        _observation = type("Observation", (), {"sandbox_ref": model.GEN})()

        async def kill(self, bound):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            finished.set()

        async def list_owned(self, bound):
            return ()

    monkeypatch.setattr(backend, "_session", lambda *args: LateSession())
    if operation == "kill":
        with pytest.raises(oj.PlacementUnavailable):
            backend.kill(lease.lease_id, model.bound(.05))
    else:
        assert journal.reap(lambda _: backend, model.bound(.05))["cleared"] == ()
    assert entered.wait(2)
    recovered = journal.recover_lease(lease.lease_id)
    try:
        before = lease.path.read_bytes()
        running_loop.call_soon_threadsafe(release.set)
        assert finished.wait(2)
        # Drain callbacks, including completion of the discarded bridge future.
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), running_loop).result(2)
        assert lease.path.read_bytes() == before
        assert entry(lease)["confirmed_killed_at"] is None
    finally:
        recovered.abandon()


def test_reaper_requires_explicit_journal_opt_in():
    lease = opened()
    lease.abandon()
    calls = []

    class Unrelated:
        def kill_journaled(self, *args):
            pytest.fail("duck-typed hook must not run")

        def kill(self, lease_id, bound):
            calls.append(lease_id)

        def list_owned(self, owner_id, bound):
            return ()

    assert journal.reap(lambda _: Unrelated(), model.bound())["cleared"] == (lease.lease_id,)
    assert calls == [lease.lease_id]


def test_opted_in_reaper_cannot_replace_reference():
    lease = opened()
    token = object()
    lease.attach_transport(token)
    lease.record_transport_ref(token, model.GEN)
    lease.abandon()

    class WrongReference(journal.JournalReapingBackend):
        def validate_reaper_context(self):
            pass

        def kill_journaled(self, *args):
            return "11111111-1111-4111-8111-111111111111"

        def list_owned(self, *args):
            return ()

    assert journal.reap(lambda _: WrongReference(), model.bound())["cleared"] == ()
    assert entry(lease)["sandbox_ref"] == model.GEN


@pytest.mark.parametrize("case", ["same", "swap", "fenced", "recovered", "wrong_adapter", "missing"])
def test_live_commit_compares_existing_generation(proto, monkeypatch, case):
    lease, stub, client = setup(proto)
    if case != "missing":
        asyncio.run(client.create(model.create_request(), model.bound()))
    if case == "fenced":
        lease.fence()
    if case == "recovered":
        lease.abandon()
        lease = journal.recover_lease(lease.lease_id)
        _, _, client = setup(proto, lease)
    before = lease.path.read_bytes()
    synced = []
    real = journal._fsync
    monkeypatch.setattr(journal, "_fsync", lambda fd: (synced.append(fd), real(fd)))
    try:
        if case == "same":
            lease.confirm_commit_ref(client, model.GEN)
            assert synced == [lease._fd]
            assert lease.path.read_bytes() == before
        else:
            with pytest.raises(ValueError):
                lease.confirm_commit_ref(object() if case == "wrong_adapter" else client,
                                         "other" if case == "swap" else model.GEN)
            assert lease.fenced and lease.path.read_bytes() == before and synced == []
    finally:
        lease.abandon()


def test_failed_session_construction_consumes_attachment(proto, monkeypatch):
    lease = opened()
    def fail(*args, **kwargs):
        raise ValueError("construction failed")
    monkeypatch.setattr(oj, "LeaseSession", fail)
    with pytest.raises(ValueError, match="construction failed"):
        oj.JournalSession(lease, proto, model.Stub(), workspace="dedicated")
    assert lease.fenced
    with pytest.raises(ValueError, match="already attached"):
        lease.attach_transport(object())
    lease.abandon()


@pytest.mark.parametrize("case", ["success", "swap", "attach_failure", "second_attach", "unattached"])
def test_driver_uses_original_journal_session(proto, monkeypatch, case):
    from phase_loop_runtime import sandbox_placement as sp
    from test_placement_driver import FarSide, walk, rungs

    class BoundBackend(FarSide, journal.LiveLeaseBackend):
        def bind_live_lease(self, lease):
            self.lease = lease
            self.fd = lease._fd
            if case == "unattached":
                return object()
            _, self.stub, self.client = setup(proto, lease)
            if case == "attach_failure":
                raise ValueError("failed after attachment")
            if case == "second_attach":
                setup(proto, lease)
            return self.client

        def check_lock(self):
            assert self.lease._fd == self.fd
            with pytest.raises(BlockingIOError):
                journal.recover_lease(self.lease.lease_id)

        def admit(self, request, bound):
            self.check_lock()
            assert request.lease_id == self.lease.lease_id
            asyncio.run(self.client.create(model.create_request(), bound))
            asyncio.run(self.client.status(bound))
            super().admit(request, bound)

        def commit(self, prepared, request, bound):
            self.check_lock()
            return sp.PlacedSandbox(
                backend="drv", sandbox_ref="other" if case == "swap" else model.GEN,
                staged_at="test", receipts=(sp.PlacementReceipt.from_backend(
                    sp.BackendReceipt("committed", "other" if case == "swap" else model.GEN,
                                      prepared.snapshot_sha256)),),
                verified={name: "backend_attested" for name in self.verify})

        def execute(self, sandbox_ref, spec, bound):
            self.check_lock()
            assert entry(self.lease)["sandbox_ref"] == sandbox_ref == model.GEN
            asyncio.run(self.client.execute(proto.ExecSandboxRequest(), bound, output_cap_bytes=0))
            return super().execute(sandbox_ref, spec, bound)

        def kill(self, lease_id, bound):
            self.check_lock()
            raise sp.PlacementUnavailable(sp._TIMEOUT)

    backend = BoundBackend("drv", None)
    monkeypatch.setitem(sp._REGISTRY, "drv", backend)
    decision = walk(rungs("drv"), last_rung="none", deadline_s=10)
    if case == "success":
        assert decision.outcome == "placed"
        assert backend.client.lease is backend.lease is decision.placement._lease
        assert entry(backend.lease)["execute_sent_at"] is not None
        assert backend.lease.path.exists()
        backend.lease.abandon()
    else:
        assert decision.outcome == "not_run"
        assert backend.lease.fenced and not backend.lease.held
        assert entry(backend.lease)["sandbox_ref"] == (model.GEN if case == "swap" else None)
        if hasattr(backend, "stub"):
            assert "exec" not in [call[0] for call in backend.stub.calls]


def test_driver_ignores_ducktyped_live_hook(monkeypatch):
    from phase_loop_runtime import sandbox_placement as sp
    from test_placement_driver import FarSide, walk, rungs
    backend = FarSide("drv", None)
    backend.bind_live_lease = lambda *_: pytest.fail("must explicitly opt in")
    monkeypatch.setitem(sp._REGISTRY, "drv", backend)
    decision = walk(rungs("drv"), deadline_s=10)
    assert decision.outcome == "placed"
    decision.placement._lease.abandon()


@pytest.mark.parametrize("late_ref", [model.GEN, "other"])
def test_driver_discards_commit_after_cancel_and_recovery(proto, monkeypatch, late_ref):
    from phase_loop_runtime import sandbox_placement as sp
    from test_placement_driver import FarSide, walk, rungs
    entered, finish, finished = threading.Event(), threading.Event(), threading.Event()
    cancelled = threading.Event()

    class BoundBackend(FarSide, journal.LiveLeaseBackend):
        def bind_live_lease(self, lease):
            self.lease, _, self.client = setup(proto, lease)
            return self.client

        def admit(self, request, bound):
            asyncio.run(self.client.create(model.create_request(), bound))

        def commit(self, prepared, request, bound):
            entered.set()
            assert finish.wait(5)
            try:
                # Even a backend attempting its own late acceptance cannot write.
                with pytest.raises(ValueError):
                    self.lease.confirm_commit_ref(self.client, late_ref)
                return sp.BackendReceipt("committed", late_ref, prepared.snapshot_sha256)
            finally:
                finished.set()

        def kill(self, lease_id, bound):
            raise sp.PlacementUnavailable(sp._TIMEOUT)

    backend = BoundBackend("drv", None)
    monkeypatch.setitem(sp._REGISTRY, "drv", backend)
    outcomes = []
    def run():
        try:
            outcomes.append(walk(rungs("drv"), last_rung="none", cancelled=cancelled))
        except sp.PlacementCancelled as exc:
            outcomes.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(3)
        cancelled.set()
        thread.join(3)
        assert not thread.is_alive()
        assert len(outcomes) == 1 and isinstance(outcomes[0], sp.PlacementCancelled)
        recovered = journal.recover_lease(backend.lease.lease_id)
        try:
            before = recovered.path.read_bytes()
            finish.set()
            assert finished.wait(3)
            assert recovered.path.read_bytes() == before
            assert entry(recovered)["sandbox_ref"] == model.GEN
            assert entry(recovered)["execute_sent_at"] is None
        finally:
            recovered.abandon()
    finally:
        finish.set()
        thread.join(3)


def test_commit_sync_failure_fences_without_changing_generation(proto, monkeypatch):
    lease, _, client = setup(proto)
    asyncio.run(client.create(model.create_request(), model.bound()))
    def fail(fd):
        raise OSError("sync failure")
    monkeypatch.setattr(journal, "_fsync", fail)
    with pytest.raises(OSError):
        lease.confirm_commit_ref(client, model.GEN)
    assert lease.fenced and entry(lease)["sandbox_ref"] == model.GEN
    lease.abandon()


@pytest.mark.parametrize("release_ownership", [False, True])
def test_split_live_session_cleanup_and_late_stream(proto, release_ownership):
    async def scenario():
        lease, stub, client = setup(proto)
        await client.create(model.create_request(), model.bound())
        await client.status(model.bound())
        entered, release = asyncio.Event(), asyncio.Event()

        async def late():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()  # model a late completion after local cancellation
            return proto.ExecSandboxEvent(exit={})

        stub.events = [late]
        handle = await client.dispatch(proto.ExecSandboxRequest(), model.bound(.02),
                                       stream_bound=model.bound(1), output_cap_bytes=0, message_cap=1)
        await entered.wait()
        assert entry(lease)["execute_sent_at"] is not None
        with pytest.raises(BlockingIOError):
            journal.recover_lease(lease.lease_id)
        if release_ownership:
            lease.abandon()
            recovered = journal.recover_lease(lease.lease_id)
            before = lease.path.read_bytes()
            with pytest.raises(ot.TransportError, match="operation_timeout"):
                await handle.wait(0)
            release.set()
            await asyncio.sleep(.01)
            assert lease.path.read_bytes() == before
            assert entry(recovered)["confirmed_killed_at"] is None
            recovered.abandon()
        else:
            stub.responses[3] = proto.ControlCancellationLeaseResponse(barrier_confirmed=True)
            stub.responses[5] = model.observation(
                lease={"lease_id": lease.lease_id, "sandbox_ref": model.GEN},
                admission_ready=False, fenced=True, execution_claimed=True,
                destruction_observed=True, cleanup_pending=False, barrier_confirmed=True)
            await client.kill(model.bound())  # original attachment, no recover_lease
            with pytest.raises(ot.TransportError, match="operation_timeout"):
                await handle.wait(0)
            release.set()
            assert lease.held and lease.path.exists()
            assert entry(lease)["confirmed_killed_at"] is not None
            # Even confirmed live KILL does not clear without complete LIST.
            lease.abandon()
        assert [c[0] for c in stub.calls].count("exec") == 1
    asyncio.run(scenario())


def test_split_no_deadline_refused_before_marker(proto):
    async def scenario():
        lease, stub, client = setup(proto)
        await client.create(model.create_request(), model.bound())
        await client.status(model.bound())
        before = lease.path.read_bytes()
        with pytest.raises(ot.UnsupportedCapability):
            await client.dispatch(proto.ExecSandboxRequest(), model.bound(), stream_bound=None,
                                  output_cap_bytes=0, message_cap=1)
        assert lease.path.read_bytes() == before
        assert "exec" not in [c[0] for c in stub.calls]
        lease.abandon()
    asyncio.run(scenario())


def test_execute_poll_expiry_fences_original_lease(proto, monkeypatch):
    model.stall_execute_poll(monkeypatch)

    async def scenario():
        lease, stub, client = setup(proto)
        try:
            await client.create(model.create_request(), model.bound())
            await client.status(model.bound())
            with pytest.raises(ot.TransportError, match="operation_timeout") as error:
                await client.execute(proto.ExecSandboxRequest(), model.bound(), output_cap_bytes=0)
            assert error.value.uncertain
            assert lease.held and lease.fenced and lease.path.exists()
            assert entry(lease)["execute_sent_at"] is not None
            assert entry(lease)["confirmed_killed_at"] is None
            before = lease.path.read_bytes()
            assert stub.stream.cancelled
            with pytest.raises(asyncio.CancelledError):
                await client._session._exec_stream._task
            with pytest.raises(ValueError, match="lease dispatch forbidden"):
                await client.dispatch(proto.ExecSandboxRequest(), model.bound(),
                                      stream_bound=model.bound(), output_cap_bytes=0, message_cap=1)
            assert lease.path.read_bytes() == before
            assert [c[0] for c in stub.calls].count("exec") == 1
        finally:
            lease.abandon()
    asyncio.run(scenario())
