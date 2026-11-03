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
from test_openshell_journal import Coordinator, bound as operation_bound
from _openshell_channel_server import stock_bindings
from phase_loop_runtime.openshell_transport import StockExecChannel, TransportError


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
        return dict(image='fake.invalid/review@sha256:' + '4' * 64, policy={},
                    policy_digest='sha256:' + '5' * 64, restart_policy='never',
                    providers=[], service_exposures=[])

    def exec_request(self, wire, end_s):
        request = self.proto.ExecSandboxRequest(stdin=wire, command=["/runtime/model-worker"],
                                               workdir="/runtime/work", no_login_shell=True,
                                               workspace_scope={'workspace': 'model'})
        request.execution_timeout.FromNanoseconds(int(end_s * 1e9))
        return request

    def validate_native(self, identity, envelope, bound):
        bound.check()
        if self.native_refuse:
            raise Refused("trusted_native_validation_refused")
        # Model witness parsing is done by validate_result; this is no attestation.


class ModelEndpoint(Coordinator):
    def __init__(self, proto, bundle, stage, root):
        super().__init__(journal.owner_id())
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

    async def call(self, op, lease_id, allowance):
        self.barrier = not self.pending
        value = await super().call(op, lease_id, allowance)
        if op == 'kill':
            self.killed = True
            if not self.pending and self.stage.root.exists():
                await asyncio.to_thread(shutil.rmtree, self.stage.root)
        return value

    async def list_owned(self, allowance):
        values = await super().list_owned(allowance)
        if self.list_present:
            return tuple(self.value(identity, 'killing') for identity in self.values)
        return values

    def unary_stream(self, path, **kwargs):
        assert path == '/openshell.v1.OpenShell/ExecSandbox'
        return self.exec

    def exec(self, request, *, timeout, wait_for_ready):
        self.calls.append('exec')
        assert self.stage.binding is not None
        assert self.backend._session.lease._entry['execute_sent_at'] is not None
        assert request.sandbox == self.backend._session.sandbox_id
        wire = request.stdin

        async def output():
            await asyncio.sleep(self.delay)
            if self.lost:
                raise TransportError('sandbox_placement_operation_timeout', uncertain=True)
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

        self.stream = ModelStream([output, self.proto.ExecSandboxEvent(exit={"exit_code": 0})])
        return self.stream


class ModelStream:
    def __init__(self, events):
        self.events, self.cancelled = iter(events), False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.cancelled:
            raise StopAsyncIteration
        try:
            value = next(self.events)
        except StopIteration:
            raise StopAsyncIteration from None
        return await value() if callable(value) else value

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def pipeline(bundle, tmp_path, monkeypatch):
    proto = stock_bindings()
    monkeypatch.setattr(sp, "ANSWER_BOUND_S", 0.5)
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
    async def channel():
        return StockExecChannel(endpoint, proto, journal.owner_id())
    exec_channel = asyncio.run_coroutine_threadsafe(channel(), loop).result(3)
    backend = ob.OpenShellBackend(endpoint, exec_channel, **args, model_only=True)
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

    def place(*, deadline=5, enabled=True, cancelled=None, required=frozenset(), roots=None):
        return sp.place(roots or [root], "none", prepared,
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
    assert endpoint.calls == ['reserve', 'create', 'status', 'status', 'exec', 'kill', 'list']
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
        ob.OpenShellBackend(endpoint, backend._exec_channel, **args)
    with pytest.raises(Refused, match='required_adapter_unavailable'):
        ob.OpenShellBackend(endpoint, backend._exec_channel, **{**args, 'stage': None}, model_only=True)
    assert place(enabled=False).outcome == 'not_run'
    assert not leases and not endpoint.calls



def test_generation_mismatch_no_execute(pipeline):
    backend, endpoint, stage, _, place, leases, *_ = pipeline
    stage.mismatch = True
    assert place().outcome == 'not_run'
    assert 'exec' not in endpoint.calls
    assert backend._session.lease._entry['sandbox_ref'] == backend._session.reference
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
    assert backend._session.lease._entry['sandbox_ref'] == backend._session.reference


@pytest.mark.parametrize('field', ['generation', 'source_sha256', 'lease_id', 'owner_id', 'workspace', None])
def test_stage_binding_fields_must_be_plain_strings(pipeline, field):
    backend, endpoint, stage, _, place, leases, *_ = pipeline

    class ForgedStr(str):
        def __eq__(self, other):
            return True

        def __ne__(self, other):
            return False

    original = stage.commit

    async def commit(binding, bundle, bound):
        await original(binding, bundle, bound)
        if field is None:
            return replace(binding)
        return replace(binding, **{field: ForgedStr('f' * 64 if field == 'source_sha256' else 'forged')})

    stage.commit = commit
    decision = place()
    if field is not None:
        assert decision.outcome == 'not_run'
        assert not backend._committed and 'exec' not in endpoint.calls
        assert backend._session.lease.fenced
        assert backend._session.lease._entry['sandbox_ref'] == backend._session.reference
        return

    assert decision.outcome == 'placed'
    result = run(decision.placement)
    assert result.exit_status == 0
    assert type(result.sandbox_ref) is str and result.sandbox_ref == backend._session.reference
    receipts = [r for r in decision.placement.receipts if r.step in ('committed', 'launched', 'completed')]
    assert {r.step for r in receipts if r.attested_by == 'runtime'} == {'committed', 'launched', 'completed'}
    for receipt in receipts:
        assert type(receipt.sandbox_ref) is str and receipt.sandbox_ref == backend._session.reference
        assert type(receipt.snapshot_sha256) is str
        assert receipt.snapshot_sha256 == backend._binding.source_sha256


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
    assert ('list' in endpoint.calls) is not pending


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
        backend.execute(backend._session.reference, decision.placement._spec, operation_bound())
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
        backend.wait(backend._session.reference, 1)
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
        ob.OpenShellBackend(endpoint, backend._exec_channel, **args, model_only=True)
    assert not endpoint.calls and not leases


def test_recovery_separate_after_pending_live_cleanup(pipeline):
    backend, endpoint, _, _, place, leases, args, proto, *_ = pipeline
    endpoint.pending = True
    decision = place()
    run(decision.placement)
    assert leases[0].path.exists() and not leases[0].held
    endpoint.pending = False
    endpoint.recovery = True
    adapter = ob.ReaperAdapter(endpoint, loop=args['loop'],
                               owner_id=args['owner_id'])
    outcome = journal.reap(lambda _: adapter, operation_bound(2))
    assert outcome == {'cleared': (leases[0].lease_id,), 'kept': ()}
    assert not leases[0].path.exists()
    assert endpoint.calls.count('exec') == 1 and endpoint.calls.count('create') == 1


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
            backend._run(effect(), operation_bound(.03))
    finally:
        resume.set()
    async def drain():
        await asyncio.sleep(.05)
    asyncio.run_coroutine_threadsafe(drain(), backend._bridge._loop).result(2)
    assert not effects and lease.fenced


def test_direct_release_shares_bound_and_never_clears(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    decision = place()
    backend.release(decision.placement.prepared, operation_bound(1))
    assert leases[0].path.exists() and leases[0].held
    assert endpoint.calls[-2:] == ['kill', 'list']


@pytest.mark.parametrize('phase', ['reserve', 'create', 'renew', 'kill', 'status'])
def test_unavailable_phase_split_no_overflow(pipeline, phase, monkeypatch):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    error = ob.CoordinatorError('unavailable', 'recovering', uncertain=phase != 'reserve')
    if phase in ('reserve', 'create', 'status'):
        endpoint.fail[phase] = error
        lookups = []
        def lookup(scheme):
            lookups.append(scheme)
            return backend if scheme == 'openshell' else None
        monkeypatch.setattr(sp, 'backend_for_scheme', lookup)
        decision = place(roots=[sandbox_policy.parse_location('openshell://fake.invalid/work'),
                                sandbox_policy.parse_location('overflow://fake.invalid/work')])
        assert ('overflow' in lookups) is (phase == 'reserve')
        assert decision.outcome == 'not_run'
        assert 'exec' not in endpoint.calls
        if phase == 'reserve':
            assert 'create' not in endpoint.calls
            assert ob.OpenShellBackend._placement_error(error, phase).code == 'sandbox_placement_unreachable'
        else:
            assert endpoint.calls[-2:] == ['kill', 'list']
            assert ob.OpenShellBackend._placement_error(error, phase).code == sp._TIMEOUT
    else:
        decision = place()
        endpoint.fail[phase] = error
        if phase == 'renew':
            backend._renew_at = 0
            with pytest.raises(sp.PlacementUnavailable, match='operation_timeout'):
                backend.renew(backend._session.reference, 10, operation_bound())
        else:
            backend.kill(leases[0].lease_id, operation_bound())
        assert endpoint.calls[-3:] == ['status', 'kill', 'list']
        assert endpoint.calls.count('exec') == 1
        assert leases[0].path.exists()


def test_renew_lifetime_exceeded_ends_before_expiry(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    place()
    backend._renew_at = 0
    expiry = backend._expiry
    endpoint.fail['renew'] = ob.CoordinatorError('lifetime_exceeded', None)
    with pytest.raises(sp.PlacementUnavailable):
        backend.renew(backend._session.reference, 3600, operation_bound())
    assert backend._end <= expiry and leases[0].fenced and leases[0].path.exists()
    assert endpoint.calls[-3:] == ['status', 'kill', 'list']


def test_renew_bounds_half_ttl_and_24h_cap(pipeline):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    place()
    backend.renew(backend._session.reference, 3600, operation_bound())
    assert 'renew' not in endpoint.calls
    backend._renew_at = 0
    backend.renew(backend._session.reference, 9000, operation_bound())
    assert endpoint.calls.count('renew') == 1
    assert backend._expiry <= backend._life_end
    backend._life_end = time.monotonic() - 1
    with pytest.raises(sp.PlacementUnavailable, match='end_reached'):
        backend.renew(backend._session.reference, 30, operation_bound())
    assert endpoint.calls.count('renew') == 1


def test_backend_start_refuses_fork_entry_without_calls(pipeline):
    backend, endpoint, _, _, _, leases, args, _, *_ = pipeline
    lease = journal.open_lease('openshell', 'openshell://fake.invalid/work')
    leases.append(lease)
    lease.abandon()
    before = lease.path.read_bytes()
    from phase_loop_runtime.openshell_journal import ForkJournalRefusal
    with pytest.raises(ForkJournalRefusal):
        ob.OpenShellBackend(endpoint, backend._exec_channel, **args, model_only=True)
    assert before == lease.path.read_bytes() and not endpoint.calls


def test_sent_reserve_timeout_never_overflows_even_without_reply_metadata(pipeline, monkeypatch):
    backend, endpoint, _, _, place, leases, *_ = pipeline
    monkeypatch.setattr(sp, 'ANSWER_BOUND_S', .05)
    reserve = endpoint.reserve
    async def lost(lease, body, allowance, *, create_body):
        await reserve(lease, body, allowance, create_body=create_body)
        await asyncio.sleep(1)
    endpoint.reserve = lost
    lookups = []
    def lookup(scheme):
        lookups.append(scheme)
        return backend if scheme == 'openshell' else None
    monkeypatch.setattr(sp, 'backend_for_scheme', lookup)
    decision = place(roots=[sandbox_policy.parse_location('openshell://fake.invalid/work'),
                            sandbox_policy.parse_location('overflow://fake.invalid/work')])
    assert decision.outcome == 'not_run' and 'overflow' not in lookups
    assert endpoint.calls.count('reserve') == 1 and 'create' not in endpoint.calls
