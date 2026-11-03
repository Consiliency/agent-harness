"""Durable coordinator lifecycle proofs; fakes confer no live qualification."""
import asyncio
from copy import deepcopy
import json
import threading
from uuid import UUID

import pytest

from _openshell_channel_server import mtls_material as mtls_material
from phase_loop_runtime import placement_lease as journal
from phase_loop_runtime import openshell_journal as oj
from phase_loop_runtime.openshell_transport import CoordinatorError, TransportError, CallerAllowance
from phase_loop_runtime.sandbox_placement import OperationBound


REF = '11111111-1111-4111-8111-111111111111'


def bound(seconds=3):
    return OperationBound(seconds, threading.Event())


def allowance():
    return CallerAllowance(bound())


def entry(lease):
    return json.loads(lease.path.read_text())


class Coordinator:
    """Deterministic server state, with loss injected after the modeled effect."""
    def __init__(self, owner):
        self.local_owner_id = owner
        self.calls = []
        self.fail = {}
        self.values = {}
        self.barrier = True
        self.present = False
        self.clock = 1000
        self.before = lambda op: None

    def validate_create(self, create, reserve):
        if create.get('invalid'):
            raise TransportError('invalid_create')

    def value(self, lease, state='ready'):
        return dict(lease_id=lease, sandbox_id=REF if state != 'reserved' else None,
                    state=state, expires_at='2030-01-01T00:00:00Z',
                    flags=dict(reserved=state != 'tombstone', create_settled=state != 'reserved',
                               exec_claimed=False, destruction_observed=state == 'destroyed',
                               cleanup_pending=state == 'killing', ready=state == 'ready', fenced=state in ('destroyed', 'killing', 'tombstone'),
                               expired=False, barrier_confirmed=state in ('destroyed', 'tombstone')),
                    binding=dict(label_matches=1 if state == 'ready' else 0, duplicates=[]), reclaims=[])

    async def call(self, op, lease, a):
        a.remaining()
        self.before(op)
        self.calls.append(op)
        if op == 'reserve':
            self.values[lease] = self.value(lease, 'reserved')
        elif op == 'create':
            self.values[lease] = self.value(lease)
        elif op == 'kill':
            self.values[lease] = self.value(lease, 'destroyed' if self.barrier else 'killing')
        if op in self.fail:
            raise self.fail.pop(op)
        return deepcopy(self.values.get(lease, self.value(lease, 'tombstone')))

    async def reserve(self, lease, body, a, *, create_body):
        return await self.call('reserve', lease, a)

    async def create(self, lease, body, a):
        return await self.call('create', lease, a)

    async def status(self, lease, a):
        return await self.call('status', lease, a)

    async def kill(self, lease, a):
        return await self.call('kill', lease, a)

    async def renew(self, lease, extend_s, a):
        assert 1 <= extend_s <= 3600
        return await self.call('renew', lease, a)

    async def list_owned(self, a):
        a.remaining()
        self.calls.append('list')
        if 'list' in self.fail:
            raise self.fail.pop('list')
        if getattr(self, 'residue', False):
            return tuple(self.value(identity, 'killing') for identity in self.values)
        return tuple(self.values.values()) if self.present else ()


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))


@pytest.fixture
def session():
    lease = journal.open_lease('openshell-model', 'openshell://fake.invalid/work')
    client = Coordinator(lease.owner_id)
    session = oj.JournalSession(lease, client)
    yield session, client, lease
    lease.abandon()


@pytest.mark.parametrize('phase', ['reserve', 'create', 'execute'])
def test_attempt_marker_is_durable_before_effect(session, phase):
    s, c, lease = session
    async def run():
        def before(op):
            if op in ('reserve', 'create'):
                assert entry(lease)[op + '_sent_at'] is not None
                assert entry(lease)['coordinator_lease_id'] == str(UUID(lease.lease_id))
        c.before = before
        if phase == 'reserve':
            await s.reserve({'ttl_s': 60}, {}, allowance())
        else:
            await s.admit({'ttl_s': 60}, {}, allowance())
            if phase == 'execute':
                lease.mark_dispatch(s, 'execute')
        assert entry(lease)[phase + '_sent_at'] is not None
        assert lease.path.exists()
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['reserve', 'create'])
def test_lost_reply_reconciles_status_then_release_without_replay(session, phase):
    s, c, lease = session
    c.fail[phase] = TransportError('sandbox_placement_operation_timeout', uncertain=True)
    async def run():
        with pytest.raises(TransportError):
            await s.admit({'ttl_s': 60}, {}, allowance())
        assert c.calls[-3:] == ['status', 'kill', 'list']
        assert c.calls.count(phase) == 1
        assert lease.fenced and lease.path.exists()
        assert entry(lease)['confirmed_killed_at'] is not None
    asyncio.run(run())


@pytest.mark.parametrize('barrier,present,listing_failure', [(False, False, False), (True, True, False),
                                                            (True, False, True)])
def test_release_requires_barrier_and_complete_inventory(session, barrier, present, listing_failure):
    s, c, lease = session
    c.barrier, c.present = barrier, present
    c.residue = present
    if listing_failure:
        c.fail['list'] = TransportError('sandbox_placement_operation_timeout', uncertain=True)
    async def run():
        await s.admit({'ttl_s': 60}, {}, allowance())
        with pytest.raises(TransportError):
            await s.release(allowance())
        assert lease.path.exists()
    asyncio.run(run())


def test_fork_entry_refuses_start_without_erasure_or_dispatch(session):
    s, c, lease = session
    old = journal.open_lease('openshell-model', 'openshell://fake.invalid/work')
    old.abandon()
    before = old.path.read_bytes()
    with pytest.raises(oj.ForkJournalRefusal):
        oj.refuse_fork_entries()
    assert old.path.read_bytes() == before and not c.calls


def test_recovered_journal_grants_cleanup_only(session):
    s, c, lease = session
    lease.abandon()
    recovered = journal.recover_lease(lease.lease_id)
    try:
        cleanup = oj.JournalSession(recovered, c)
        async def run():
            with pytest.raises((ValueError, TransportError)):
                await cleanup.admit({'ttl_s': 60}, {}, allowance())
            await cleanup.release(allowance())
            assert c.calls == ['kill', 'list']
        asyncio.run(run())
        assert recovered.path.exists()
    finally:
        recovered.abandon()


@pytest.mark.parametrize('state', ['reserved', 'killing', 'tombstone', 'destroyed', 'expired'])
def test_inventory_keeps_reservations_and_killing_filters_terminal(session, state):
    s, c, lease = session
    c.values[s.client_uuid] = c.value(s.client_uuid, state)
    if state == 'expired':
        c.values[s.client_uuid]['flags'].update(expired=True, fenced=True, barrier_confirmed=True)
    c.present = True
    pairs = asyncio.run(s.list_owned(allowance()))
    assert pairs == (() if state in ('tombstone', 'destroyed', 'expired') else ((s.reference, lease.lease_id),))
    assert s.inventory[0]['state'] == state


def test_generation_binding_is_immutable(session):
    s, c, lease = session
    async def run():
        await s.admit({'ttl_s': 60}, {}, allowance())
        c.values[s.client_uuid]['sandbox_id'] = '22222222-2222-4222-8222-222222222222'
        with pytest.raises(TransportError):
            await s.status(allowance())
    asyncio.run(run())
    assert lease.fenced and entry(lease)['sandbox_ref'] == s.reference


def test_reserve_collision_journals_fresh_uuid_retries_once_records_bug(session):
    s, c, lease = session
    original = s.client_uuid
    c.fail['reserve'] = CoordinatorError('invalid_request', None, uncertain=False)
    seen = []
    def before(op):
        if op == 'reserve':
            seen.append(entry(lease)['coordinator_lease_id'])
    c.before = before
    asyncio.run(s.admit({'ttl_s': 60}, {}, allowance()))
    assert len(seen) == 2 and seen[0] == original and seen[1] != original
    assert entry(lease)['reserve_collision'] is True
    assert entry(lease)['coordinator_lease_id'] == seen[1]
    assert c.calls.count('create') == 1


@pytest.mark.parametrize('phase', ['reserve', 'create'])
def test_invalid_request_reserve_holds_nothing_create_releases_first(session, phase):
    s, c, lease = session
    if phase == 'reserve':
        c.validate_create = lambda *_: (_ for _ in ()).throw(TransportError('invalid_create'))
    else:
        c.fail[phase] = CoordinatorError('invalid_request', None, uncertain=True)
    async def run():
        with pytest.raises(TransportError):
            await s.admit({'ttl_s': 60}, {}, allowance())
    asyncio.run(run())
    assert c.calls == ([] if phase == 'reserve' else ['reserve', 'create', 'status', 'kill', 'list'])
    assert lease.path.exists()


@pytest.mark.parametrize('phase', ['reserve', 'create', 'execute'])
def test_crash_at_durable_marker_recovers_cleanup_only(session, phase):
    s, c, lease = session
    async def run():
        if phase != 'reserve':
            await s.admit({'ttl_s': 60}, {}, allowance())
        else:
            lease.mark_dispatch(s, 'reserve')
        if phase == 'execute':
            lease.mark_dispatch(s, 'execute')
    asyncio.run(run())
    lease.abandon()
    recovered = journal.recover_lease(lease.lease_id)
    try:
        after = oj.JournalSession(recovered, Coordinator(lease.owner_id))
        with pytest.raises(ValueError):
            asyncio.run(after.reserve({'ttl_s': 60}, {}, allowance()))
        assert recovered.path.exists()
    finally:
        recovered.abandon()


@pytest.mark.parametrize('flag', ['fenced', 'expired'])
def test_fenced_or_expired_before_launch_releases_without_exec(session, flag):
    s, c, lease = session
    async def run():
        await s.admit({'ttl_s': 60}, {}, allowance())
        c.values[s.client_uuid]['flags'][flag] = True
        with pytest.raises(TransportError):
            await s.dispatch(object(), allowance(), stream_allowance=allowance(),
                             output_cap_bytes=1, message_cap=1)
    asyncio.run(run())
    assert c.calls[-4:] == ['status', 'status', 'kill', 'list']
    assert entry(lease)['execute_sent_at'] is None
    assert lease.fenced and lease.path.exists()


def test_snapshot_clock_over_60s_expires_then_restarts(mtls_material):
    from _openshell_channel_server import json_coordinator
    from test_openshell_transport import wire
    from phase_loop_runtime.openshell_transport import CoordinatorClient
    async def run():
        clock = [100.0]
        page = wire('first-page')
        # No lease changes: the only failure is snapshot age at the next page.
        expired = dict(code='snapshot_expired', reason=None, lease_id=None)
        async def after_sixty_seconds():
            clock[0] += 61
            return 409, expired
        complete = deepcopy(page)
        complete['next_page_token'] = None
        complete['snapshot'] = 'fresh-snapshot'
        async with json_coordinator(mtls_material, [page, after_sixty_seconds, complete]) as (config, calls):
            client = CoordinatorClient(config, local_owner_id='journal-owner', clock=lambda: clock[0])
            values = await client.list_owned(allowance())
            assert values == tuple(complete['items'])
            assert len(calls) == 3
            assert 'page_token=' in calls[1][0] and 'page_token=' not in calls[2][0]
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['reserve', 'create', 'execute'])
def test_fsync_failure_at_attempt_marker_prevents_effect(session, monkeypatch, phase):
    s, c, lease = session
    async def run():
        if phase == 'create':
            await s.reserve({'ttl_s': 60}, {}, allowance())
        elif phase == 'execute':
            await s.admit({'ttl_s': 60}, {}, allowance())
        before = list(c.calls)
        def fail(fd):
            raise OSError('synthetic sync failure')
        monkeypatch.setattr(journal, '_fsync', fail)
        with pytest.raises(OSError):
            if phase == 'reserve':
                await s.reserve({'ttl_s': 60}, {}, allowance())
            elif phase == 'create':
                await s.create({}, allowance())
            else:
                lease.mark_dispatch(s, 'execute')
        assert c.calls == before and lease.fenced
    asyncio.run(run())


def test_duplicate_binding_retains_debt_until_every_match_destroyed(session):
    s, c, lease = session
    c.fail['create'] = CoordinatorError('duplicate_binding', None)
    c.residue = True
    async def run():
        with pytest.raises(TransportError, match='release_unconfirmed'):
            await s.admit({'ttl_s': 60}, {}, allowance())
        assert lease.path.exists() and lease.fenced
        c.residue = False
        await s.release(allowance())
        assert lease.path.exists()  # adapter proof alone never erases the journal
    asyncio.run(run())


def test_coordinator_restart_unknown_lease_killed_to_unseen_tombstone(session):
    s, c, lease = session
    asyncio.run(s.admit({'ttl_s': 60}, {}, allowance()))
    lease.abandon()
    # Fresh server/client loses all state; the recovered process must never adopt.
    restarted = Coordinator(lease.owner_id)
    restarted.fail['status'] = CoordinatorError('unknown_lease', None)
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    def serve():
        loop.call_soon(ready.set)
        loop.run_forever()
    thread = threading.Thread(target=serve)
    thread.start()
    assert ready.wait(2)
    try:
        adapter = oj.ReaperAdapter(restarted, loop=loop, owner_id=lease.owner_id)
        result = journal.reap(lambda _: adapter, bound())
        assert result == {'cleared': (lease.lease_id,), 'kept': ()}
        assert restarted.calls == ['status', 'kill', 'list']
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(2)
        loop.close()


def test_unseen_kill_tombstone_is_terminal_but_kill_still_required(session):
    s, c, lease = session
    c.values[s.client_uuid] = c.value(s.client_uuid, 'tombstone')
    c.present = True
    async def run():
        assert await s.list_owned(allowance()) == ()
        assert entry(lease)['confirmed_killed_at'] is None
        await s.release(allowance())
        assert 'kill' in c.calls and lease.path.exists()
    asyncio.run(run())


def test_duplicate_and_reclaim_evidence_is_durable_and_secret_free(session):
    s, c, lease = session
    async def run():
        await s.admit({'ttl_s': 60}, {}, allowance())
        value = c.values[s.client_uuid]
        value['binding'] = dict(label_matches=2, duplicates=[REF], diagnostic='SECRET')
        value['reclaims'] = [dict(sandbox_id=REF, reason='duplicate_binding',
                                 outcome='destroy_pending', at='2026-11-02T00:00:00Z', diagnostic='SECRET')]
        value['diagnostic'] = 'SECRET'
        await s.status(allowance())
        evidence = entry(lease)['coordinator_evidence']
        assert evidence['binding']['duplicates'] == [REF]
        assert evidence['reclaims'][0]['outcome'] == 'destroy_pending'
        assert 'SECRET' not in lease.path.read_text()
    asyncio.run(run())
