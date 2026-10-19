"""Model-only end-to-end integration; no actual RPC, server, isolation or VM proof."""
import asyncio
from dataclasses import replace
import json
import shutil
import threading
import time

import pytest

from phase_loop_runtime import openshell_backend as ob, placement_lease as journal
from phase_loop_runtime import sandbox_placement as sp, sandbox_policy
from phase_loop_runtime.openshell_artifacts import Bound, Refused, SourceBundle, canonical, init_tree, scan
from phase_loop_runtime.openshell_worker import read_request, run_worker
from test_openshell_artifacts import bound as bound, bundle as bundle, limits as limits, repository as repository
from test_openshell_worker import SyntheticRuntime, login
import test_openshell_transport as model


class ModelStage:
    def __init__(self, root):
        self.root = root
        self.bundle = None
        self.calls = 0
        self.binding = None
        self.mismatch = False
        self.entered = threading.Event()
        self.resume = threading.Event()
        self.hold = False

    def validate_configuration(self):
        assert self.root.parent.is_dir() and not self.root.exists()

    async def commit(self, binding, bundle, bound):
        self.calls += 1
        limits = Bound(time.monotonic() + bound.timeout_s, bound.cancelled.is_set)
        await asyncio.to_thread(init_tree, self.root, bundle, limits)
        files = await asyncio.to_thread(scan, self.root, bundle.limits, limits)
        self.bundle = SourceBundle(bundle.base, bundle.tree, files, bundle.owned_paths, bundle.limits)
        self.bundle.validate()
        assert self.bundle.sha256 == binding.source_sha256
        self.entered.set()
        if self.hold:
            # Deliberately adversarial late adapter, even after future cancellation.
            try:
                while not self.resume.is_set():
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                while not self.resume.is_set():
                    await asyncio.sleep(0.01)
        self.binding = binding
        return replace(binding, generation="00000000-0000-0000-0000-000000000001") if self.mismatch else binding


class ModelWorker:
    image_sha256 = "4" * 64

    def __init__(self, proto):
        self.proto = proto
        self.native_refuse = False

    def validate_configuration(self):
        request = self.exec_request(b'model', 1)
        assert request.no_login_shell and not request.environment

    def create_request(self):
        return self.proto.CreateSandboxRequest(spec={"restart_policy": 1, "policy": {}})

    def exec_request(self, wire, end_s):
        request = self.proto.ExecSandboxRequest(stdin=wire, command=["/runtime/model-worker"],
                                               workdir="/runtime/work", no_login_shell=True)
        request.execution_timeout.FromNanoseconds(int(end_s * 1e9))
        return request

    def validate_native(self, identity, envelope, bound):
        bound.check()
        if self.native_refuse:
            raise Refused("trusted_native_validation_refused")
        # Model witness parsing is done by validate_result; this is no attestation.


class ModelEndpoint:
    def __init__(self, proto, bundle, stage, root):
        self.proto, self.bundle, self.stage, self.root = proto, bundle, stage, root
        self.calls = []
        self.pending = False
        self.killed = False
        self.delay = 0
        self.lost = False
        self.corrupt = False
        self.list_present = False
        self.native_bad = False
        self.recovery = False
        self.stream = None
        self.runtime = SyntheticRuntime(root)
        self.backend = None

    async def ControlCancellationLease(self, request, *, timeout):
        self.calls.append(request.operation)
        lease = self.backend._session.lease
        if self.recovery:
            assert not lease.held
            assert request.operation in (3, 4, 5)
        else:
            assert lease.held
            with pytest.raises(BlockingIOError):
                journal.recover_lease(lease.lease_id)
        if request.operation == 2:
            assert lease._entry['create_sent_at'] is not None
            return self.proto.ControlCancellationLeaseResponse(
                sandbox={"metadata": {"id": model.GEN, "workspace": "model"}})
        if request.operation == 3:
            self.killed = True
            if not self.pending and self.stage.root.exists():
                # Only the fixture-owned materialized tree; quarantine is client-owned.
                await asyncio.to_thread(shutil.rmtree, self.stage.root)
            return self.proto.ControlCancellationLeaseResponse(barrier_confirmed=not self.pending)
        if request.operation == 4:
            assert self.killed
            return self.proto.ControlCancellationLeaseResponse(entries=[
                {"lease_id": lease.lease_id, "sandbox_ref": model.GEN}] if self.list_present else [])
        assert request.operation == 5
        return self.proto.ControlCancellationLeaseResponse(
            lease={"lease_id": lease.lease_id, "sandbox_ref": model.GEN},
            admission_ready=not self.killed, create_settled=True,
            fenced=self.killed, destruction_observed=self.killed and not self.pending,
            cleanup_pending=not self.killed or self.pending,
            barrier_confirmed=self.killed and not self.pending)

    def ExecCancellationLease(self, request, *, timeout):
        self.calls.append("exec")
        assert self.stage.binding is not None
        assert self.backend._session.lease._entry['execute_sent_at'] is not None
        assert request.lease_id == self.stage.binding.lease_id
        wire = request.exec.stdin  # Memory only, never recorded in call history.

        async def output():
            await asyncio.sleep(self.delay)
            if self.lost:
                raise model.RpcFailure("UNAVAILABLE")
            identity = read_request(wire, self.bundle, 50000).identity
            envelope = await asyncio.to_thread(
                run_worker, wire, self.stage.bundle, expected_identity=identity, request_cap=50000,
                runtime=self.runtime, scratch_parent=self.root,
                cancelled=lambda: self.backend._session.lease.fenced)
            if self.corrupt or self.native_bad:
                data = json.loads(envelope)
                if self.corrupt:
                    data['patch_sha256'] = '0' * 64
                else:
                    data['native'] = ''
                    from phase_loop_runtime.openshell_artifacts import digest
                    data['native_sha256'] = digest(b'')
                envelope = canonical(data)
            return self.proto.ExecSandboxEvent(stdout={"data": envelope})

        self.stream = model.Stream([output, self.proto.ExecSandboxEvent(exit={"exit_code": 0})])
        return self.stream


@pytest.fixture(params=["compact", "generated"])
def pipeline(request, bundle, tmp_path, monkeypatch):
    proto = model.bindings() if request.param == "compact" else model.generated_bindings()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def serve():
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor(timeout=5))
        loop.close()

    thread = threading.Thread(target=serve)
    thread.start()
    assert ready.wait(2)
    stage, worker = ModelStage(tmp_path / 'stage'), ModelWorker(proto)
    endpoint = ModelEndpoint(proto, bundle, stage, tmp_path)
    args = dict(loop=loop, workspace="model", owner_id=journal.owner_id(), bundle=bundle,
                stage=stage, worker=worker, task="Edit the owned file",
                tests=("synthetic-content-check",), login_store=login, request_cap=50000,
                message_cap=10, quarantine=tmp_path / "quarantine")
    backend = ob.OpenShellBackend(proto, endpoint, **args, model_only=True)
    endpoint.backend = backend
    root = sandbox_policy.parse_location("openshell://model.invalid/workspace")
    prepared = sp.Prepared(tmp_path, tmp_path, bundle.sha256, "source",
                           sp.PlacementReceipt.from_backend(sp.BackendReceipt("prepared", "source", bundle.sha256)))
    base_request = sp.PlacementRequest("implementation", "model", "fixture", bundle.sha256,
                                       5, sp.EgressNeeds(), workload="implementation")
    monkeypatch.setattr(sp, "backend_for_scheme", lambda scheme: backend)
    leases = []

    def open_lease(name, root):
        lease = journal.open_lease(name, root)
        leases.append(lease)
        return lease

    def place(*, deadline=5, enabled=True, cancelled=None, required=frozenset()):
        return sp.place([root], "none", prepared,
                        lambda root: replace(base_request, deadline_s=deadline, required_capabilities=required),
                        open_lease, preflight=lambda: None, seal=backend.seal,
                        driver_enabled=enabled, cancelled=cancelled or threading.Event())

    try:
        yield backend, endpoint, stage, worker, place, leases, args, proto, prepared, base_request
    finally:
        stage.resume.set()
        async def drain():
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.run_coroutine_threadsafe(drain(), loop).result(5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(6)
        assert not thread.is_alive()
        for lease in leases:
            if lease.held:
                lease.abandon()


def run(placement, cancelled=None):
    return sp.run_placed(placement, on_progress=None, cancelled=cancelled or threading.Event())


def test_driver_model_edit_test_quarantine_cleanup(pipeline, repository):
    backend, endpoint, stage, worker, place, leases, *_ = pipeline
    decision = place()
    assert decision.outcome == "placed"
    lease = leases[0]
    assert backend._session.lease is lease and lease.held
    result = run(decision.placement)
    data = json.loads(result.result)
    assert data['request_sha256'] == backend._wire_digest
    assert data['worker_request_sha256'] == backend._identity.request_sha256
    assert data['request_sha256'] != data['worker_request_sha256']
    assert data['required_next_step'] == 'isolated_same_base_retest_and_owner_acceptance'
    assert backend._quarantine.joinpath('untrusted.patch').is_file()
    assert (repository[0] / 'owned.txt').read_bytes() == b'before\n'
    assert endpoint.runtime.test_calls == 1
    assert stage.calls == 1 and endpoint.calls.count('exec') == 1
    assert endpoint.calls == [2, 5, 'exec', 3, 5, 4]
    assert not lease.held and not lease.path.exists()
    assert not stage.root.exists()
    assert backend.capabilities() == frozenset()


@pytest.mark.parametrize('deadline', [None, float('inf'), float('nan'), 0, -1])
def test_finite_only_before_effects(pipeline, deadline):
    *_, place, leases, args, proto, prepared, request = pipeline
    assert place(deadline=deadline).outcome == 'not_run'
    assert not leases and not pipeline[1].calls


def test_production_and_gate_closed(pipeline):
    backend, endpoint, _, _, place, leases, args, proto, *_ = pipeline
    with pytest.raises(Refused, match='production_adapters_unqualified'):
        ob.OpenShellBackend(proto, endpoint, **args)
    with pytest.raises(Refused, match='required_adapter_unavailable'):
        ob.OpenShellBackend(proto, endpoint, **{**args, 'stage': None}, model_only=True)
    assert place(enabled=False).outcome == 'not_run'
    assert not leases and not endpoint.calls
    with pytest.raises(ob.UnsupportedCapability):
        backend.renew('anything', 10, model.bound())


def test_generation_mismatch_no_execute(pipeline):
    backend, endpoint, stage, _, place, leases, *_ = pipeline
    stage.mismatch = True
    assert place().outcome == 'not_run'
    assert 'exec' not in endpoint.calls
    assert backend._session.lease._entry['sandbox_ref'] == model.GEN
    assert not backend._committed


@pytest.mark.parametrize('receipt_kind', ['foreign', 'subclass', 'digest'])
def test_stage_receipt_must_be_exact_binding(pipeline, receipt_kind):
    backend, endpoint, stage, _, place, leases, *_ = pipeline

    class LyingReceipt:
        def __ne__(self, other):
            return False

    class BindingSubclass(ob.StageBinding):
        def __ne__(self, other):
            return False

    original = stage.commit

    async def commit(binding, bundle, bound):
        await original(binding, bundle, bound)
        if receipt_kind == 'digest':
            return replace(binding, source_sha256='0' * 64)
        receipt = (LyingReceipt() if receipt_kind == 'foreign' else
                   BindingSubclass(**vars(binding)))
        if receipt_kind == 'foreign':
            receipt.generation = binding.generation
            receipt.source_sha256 = binding.source_sha256
        return receipt

    stage.commit = commit
    assert place().outcome == 'not_run'
    assert not backend._committed and 'exec' not in endpoint.calls
    assert backend._session.lease._entry['sandbox_ref'] == model.GEN


@pytest.mark.parametrize('failure', ['lost', 'corrupt', 'native_bad', 'native_refuse'])
def test_untrusted_or_lost_result_refused_no_replay(pipeline, failure):
    backend, endpoint, _, worker, place, leases, *_ = pipeline
    setattr(worker if failure == 'native_refuse' else endpoint, failure, True)
    decision = place()
    with pytest.raises(sp.PlacementUnavailable, match='lost_after_launch'):
        run(decision.placement)
    assert endpoint.calls.count('exec') == 1
    assert not backend._quarantine.exists()
    assert not leases[0].path.exists()


@pytest.mark.parametrize('pending', [True, False])
def test_pending_or_listed_release_retains_journal(pipeline, pending):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    endpoint.pending = pending
    endpoint.list_present = not pending
    decision = place()
    result = run(decision.placement)
    assert result.exit_status == 0
    assert 'sandbox_placement_release_unconfirmed' in decision.placement.notices
    assert leases[0].path.exists() and not leases[0].held
    assert (4 in endpoint.calls) is not pending


def test_delayed_output_beyond_dispatch_bound(pipeline, monkeypatch):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    monkeypatch.setattr(sp, 'ANSWER_BOUND_S', 0.15)
    endpoint.delay = 0.35
    decision = place()
    assert not decision.placement._launch_failed
    assert run(decision.placement).exit_status == 0
    assert endpoint.calls.count('exec') == 1


def test_fixed_end_does_not_renew_or_replay(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    endpoint.delay = 1
    decision = place(deadline=0.15)
    with pytest.raises(sp.PlacementUnavailable):
        run(decision.placement)
    assert endpoint.stream.cancelled
    assert not backend._quarantine.exists()
    assert endpoint.calls.count('exec') == 1


def test_cancel_before_result_suppresses_quarantine(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    endpoint.delay = 0.3
    cancelled = threading.Event()
    decision = place(cancelled=cancelled)
    cancelled.set()
    with pytest.raises(sp.PlacementCancelled):
        run(decision.placement, cancelled)
    assert endpoint.stream.cancelled
    assert not backend._quarantine.exists()
    assert endpoint.calls.count('exec') == 1


def test_duplicate_exec_and_seal_refused(pipeline):
    backend, endpoint, _, _, place, leases, *rest = pipeline
    decision = place()
    with pytest.raises(Refused, match='execute_not_permitted'):
        backend.execute(model.GEN, decision.placement._spec, model.bound())
    request = replace(rest[-1], owner_id=leases[0].owner_id, lease_id=leases[0].lease_id)
    with pytest.raises(Refused, match='seal_not_permitted'):
        backend.seal(request)
    assert run(decision.placement).exit_status == 0
    assert endpoint.calls.count('exec') == 1


def test_late_commit_after_cancel_and_ownership_release(pipeline):
    backend, endpoint, stage, _, place, leases, *_ = pipeline
    stage.hold = True
    cancelled = threading.Event()
    failures = []
    def dispatch():
        try:
            place(cancelled=cancelled)
        except sp.PlacementCancelled:
            failures.append('cancelled')
    thread = threading.Thread(target=dispatch)
    thread.start()
    assert stage.entered.wait(3)
    cancelled.set()
    thread.join(3)
    assert not thread.is_alive() and failures == ['cancelled']
    assert not leases[0].held
    stage.resume.set()
    async def settled():
        for _ in range(100):
            if stage.binding is not None:
                return
            await asyncio.sleep(.01)
        raise AssertionError('late stage did not settle')
    asyncio.run_coroutine_threadsafe(settled(), backend._bridge._loop).result(2)
    assert not backend._committed and 'exec' not in endpoint.calls
    assert leases[0]._entry['execute_sent_at'] is None


def test_completed_stream_after_ownership_release_refused(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    decision = place()
    async def completed():
        await backend._stream._task
    asyncio.run_coroutine_threadsafe(completed(), backend._bridge._loop).result(3)
    # Release the original handle without authorizing a result or clearing evidence.
    leases[0].abandon()
    with pytest.raises(ValueError, match='live lease not owned'):
        backend.wait(model.GEN, 1)
    assert not backend._quarantine.exists() and leases[0].path.exists()


def test_cancel_wins_simultaneous_result(pipeline, monkeypatch):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    cancelled = threading.Event()
    decision = place(cancelled=cancelled)
    original = backend.wait
    def finished(ref, seconds):
        result = original(ref, seconds)
        if isinstance(result, sp.ExecResult):
            cancelled.set()
        return result
    monkeypatch.setattr(backend, 'wait', finished)
    with pytest.raises(sp.PlacementCancelled):
        run(decision.placement, cancelled)
    assert not any(r.step == 'completed' for r in decision.placement.receipts)
    assert not leases[0].path.exists()


def test_cancel_wins_failed_launch(pipeline, monkeypatch):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    cancelled = threading.Event()
    def failed(*args):
        cancelled.set()
        raise Refused('uncertain_dispatch')
    monkeypatch.setattr(backend, 'execute', failed)
    decision = place(cancelled=cancelled)
    assert decision.placement._launch_failed
    with pytest.raises(sp.PlacementCancelled):
        run(decision.placement, cancelled)
    assert not leases[0].path.exists()


def test_abandon_cancels_silent_collector_without_wait(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    endpoint.delay = 2
    place()
    leases[0].abandon()
    async def stopped():
        for _ in range(100):
            if endpoint.stream.cancelled:
                return
            await asyncio.sleep(.01)
        raise AssertionError('ownership release did not stop stream')
    asyncio.run_coroutine_threadsafe(stopped(), backend._bridge._loop).result(2)
    assert leases[0].path.exists() and not backend._quarantine.exists()


def test_unqualified_adapter_refuses_before_attachment(pipeline):
    backend, endpoint, stage, worker, place, leases, args, proto, *_ = pipeline
    def refuse():
        raise Refused('fixture_configuration_unavailable')
    stage.validate_configuration = refuse
    with pytest.raises(Refused, match='fixture_configuration_unavailable'):
        ob.OpenShellBackend(proto, endpoint, **args, model_only=True)
    assert not endpoint.calls and not leases


def test_recovery_separate_after_pending_live_cleanup(pipeline):
    backend, endpoint, _, _, place, leases, args, proto, *_ = pipeline
    endpoint.pending = True
    decision = place()
    run(decision.placement)
    assert leases[0].path.exists() and not leases[0].held
    endpoint.pending = False
    endpoint.recovery = True
    adapter = ob.ReaperAdapter(proto, endpoint, loop=args['loop'], workspace='model',
                               owner_id=args['owner_id'])
    outcome = journal.reap(lambda _: adapter, model.bound(2))
    assert outcome == {'cleared': (leases[0].lease_id,), 'kept': ()}
    assert not leases[0].path.exists()
    assert endpoint.calls.count('exec') == 1 and endpoint.calls.count(2) == 1


def test_c5_is_not_synthesized(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    assert place(required=frozenset({'one_shot_secret_channel'})).outcome == 'not_run'
    assert not leases and not endpoint.calls


def test_late_native_validation_after_cancel_cannot_quarantine(pipeline):
    backend, endpoint, _, worker, place, leases, *_ = pipeline
    entered, resume, settled = threading.Event(), threading.Event(), threading.Event()
    def validate(identity, envelope, bound):
        entered.set()
        assert resume.wait(3)
        try:
            bound.check()
        finally:
            settled.set()
    worker.validate_native = validate
    cancelled = threading.Event()
    decision = place(cancelled=cancelled)
    failures = []
    def waiting():
        try:
            run(decision.placement, cancelled)
        except sp.PlacementCancelled:
            failures.append('cancelled')
    thread = threading.Thread(target=waiting)
    thread.start()
    try:
        assert entered.wait(3)
        cancelled.set()
        thread.join(2)
        assert not thread.is_alive() and failures == ['cancelled']
        assert not leases[0].held
    finally:
        resume.set()
        thread.join(3)
    assert settled.wait(2)
    assert not backend._quarantine.exists()


def test_bridge_timeout_before_loop_starts_has_no_late_effect(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    # Attach locally, then hold the loop before scheduling a CREATE coroutine.
    lease = journal.open_lease('openshell', 'openshell://model.invalid/workspace')
    leases.append(lease)
    backend.bind_live_lease(lease)
    entered, resume = threading.Event(), threading.Event()
    def hold():
        entered.set()
        assert resume.wait(3)
    backend._bridge._loop.call_soon_threadsafe(hold)
    assert entered.wait(2)
    effects = []
    async def effect():
        effects.append('late')
    try:
        with pytest.raises(sp.PlacementUnavailable, match='operation_timeout'):
            backend._run(effect(), model.bound(.03))
    finally:
        resume.set()
    async def drain():
        await asyncio.sleep(.05)
    asyncio.run_coroutine_threadsafe(drain(), backend._bridge._loop).result(2)
    assert not effects and lease.fenced


def test_direct_release_shares_bound_and_never_clears(pipeline, monkeypatch):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    decision = place()
    original_kill, original_list = backend.kill, backend.list_owned
    seen = []
    def kill(lease_id, bound):
        seen.append(bound.timeout_s)
        threading.Event().wait(.03)
        return original_kill(lease_id, bound)
    def listing(owner, bound):
        seen.append(bound.timeout_s)
        return original_list(owner, bound)
    monkeypatch.setattr(backend, 'kill', kill)
    monkeypatch.setattr(backend, 'list_owned', listing)
    backend.release(decision.placement.prepared, model.bound(1))
    assert 0 < seen[1] < seen[0] - .02
    assert leases[0].path.exists() and leases[0].held
