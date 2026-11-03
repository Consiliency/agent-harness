"""Offline coordinator wire tests; no live qualification."""
import asyncio
import threading
from uuid import uuid4
import pytest
from phase_loop_runtime import openshell_transport as ot
from phase_loop_runtime.sandbox_placement import OperationBound


GEN = 'd1e50366-0a54-4df0-b778-45b37b391df6'
OTHER_GEN = 'b971370c-a1b8-432a-a987-cef35cbc474b'
run = asyncio.run


def bound(seconds=1):
    return OperationBound(seconds, threading.Event())


from copy import deepcopy
import json
from pathlib import Path
from _openshell_channel_server import json_coordinator, mtls_material as mtls_material

_CONTRACT = Path(__file__).parents[1] / 'src/phase_loop_runtime/contracts/placement'
_WIRE = json.loads((_CONTRACT / 'vectors/wire.json').read_text())


def wire(name, kind=None):
    return deepcopy(next(v['value'] for v in _WIRE['valid']
                         if v['name'] == name and (kind is None or v['type'] == kind)))


def coordinator(config):
    return ot.CoordinatorClient(config, local_owner_id='journal-owner')


@pytest.mark.parametrize('vector', [v for v in _WIRE['valid'] if v['type'] == 'LeaseStatus'],
                         ids=lambda v: v['name'])
def test_coordinator_status_vectors(mtls_material, vector):
    async def scenario():
        async with json_coordinator(mtls_material, [vector['value']]) as (config, calls):
            client = coordinator(config)
            result = await client.status(vector['value']['lease_id'], ot.CallerAllowance(bound()))
            assert result['flags'] == vector['value']['flags']
            assert client.local_owner_id == 'journal-owner' != config.owner_cn
            assert 1 <= int(calls[0][1]['X-Deadline-Ms']) <= 30000
    run(scenario())


def test_coordinator_lifecycle_and_complete_inventory(mtls_material):
    async def scenario():
        reserve = wire('reserve-leg-min-ttl')
        create = wire('deep-policy')
        create['service_exposures'] = []
        reserve['policy_digest'] = create['policy_digest']
        reserved = wire('reserved')
        lease = reserved['lease_id']
        ready = deepcopy(reserved)
        ready.update(state='ready', sandbox_id=GEN)
        ready['flags'].update(create_settled=True, ready=True)
        destroyed = deepcopy(ready)
        destroyed.update(state='destroyed')
        destroyed['flags'].update(fenced=True, destruction_observed=True, barrier_confirmed=True)
        first, last = wire('first-page'), wire('last-page')
        replies = [reserved, ready, ready, ready, destroyed, first, last]
        async with json_coordinator(mtls_material, replies) as (config, calls):
            client, allowance = coordinator(config), ot.CallerAllowance(bound(2))
            await client.reserve(lease, reserve, allowance)
            await client.create(lease, create, allowance)
            await client.status(lease, allowance)
            await client.renew(lease, 3600, allowance)
            await client.kill(lease, allowance)
            # Use a separate observer: the historical vector is a prior snapshot.
            inventory = await coordinator(config).list_owned(allowance)
            assert len(inventory) == 1
            assert [c[0].split()[0] for c in calls] == ['POST', 'POST', 'GET', 'POST', 'POST', 'GET', 'GET']
            assert calls[0][2] == reserve and calls[1][2] == create
            assert calls[3][2] == {'extend_s': 3600}
            assert all('owner' not in (c[2] or {}) and 'client' not in (c[2] or {}) for c in calls)
            deadlines = [int(c[1]['X-Deadline-Ms']) for c in calls]
            assert deadlines == sorted(deadlines, reverse=True)
            assert calls[-1][0].startswith('GET /v1/leases?page_size=200&page_token=')
    run(scenario())


@pytest.mark.parametrize('fault', ['missing', 'wrong-lease', 'unknown-code', 'prose-5xx', 'changed-uuid', 'regressed'])
def test_coordinator_faults_keep_cleanup_and_poison_dispatch(mtls_material, fault):
    async def scenario():
        good = wire('reserved')
        good.update(state='ready', sandbox_id=GEN)
        good['flags'].update(create_settled=True, ready=True)
        bad = deepcopy(good)
        if fault == 'missing': del bad['flags']['reserved']
        if fault == 'wrong-lease': bad['lease_id'] = str(uuid4())
        if fault == 'unknown-code': bad = (503, {'code': 'SECRET-NEW', 'reason': None, 'lease_id': good['lease_id']})
        if fault == 'prose-5xx': bad = (503, b'SECRET nothing held')
        if fault == 'changed-uuid': bad['sandbox_id'] = OTHER_GEN
        if fault == 'regressed': bad['flags']['create_settled'] = False
        async with json_coordinator(mtls_material, [good, bad, wire('destroyed')]) as (config, _):
            client = coordinator(config)
            allowance = ot.CallerAllowance(bound())
            await client.status(good['lease_id'], allowance)
            with pytest.raises(ot.TransportError) as error:
                await client.status(good['lease_id'], allowance)
            assert error.value.uncertain
            assert 'SECRET' not in str(error.value)
            assert good['lease_id'] in client.cleanup_obligations
            assert good['lease_id'] in client.poisoned_leases
    run(scenario())


@pytest.mark.parametrize('vector', [v for v in _WIRE['valid'] if v['type'] == 'ErrorBody'], ids=lambda v: v['name'])
def test_coordinator_closed_errors(mtls_material, vector):
    async def scenario():
        lease = wire('reserved')['lease_id']
        async with json_coordinator(mtls_material, [(503, vector['value'])]) as (config, _):
            with pytest.raises(ot.CoordinatorError) as error:
                await coordinator(config).reserve(lease, wire('reserve-leg-min-ttl'), ot.CallerAllowance(bound()))
            assert error.value.code == vector['value']['code']
            assert error.value.reason == vector['value']['reason']
    run(scenario())


@pytest.mark.parametrize('mode', ['changed', 'expired', 'stale-token', 'age'])
def test_coordinator_snapshot_restarts_without_partial_result(mtls_material, mode):
    async def scenario():
        first, last = wire('first-page'), wire('last-page')
        clock = [0.0]
        async def second():
            if mode == 'age': clock[0] = 61
            if mode == 'expired':
                return (409, {'code': 'snapshot_expired', 'reason': None, 'lease_id': None})
            value = deepcopy(last)
            if mode == 'changed': value['snapshot'] = 'different'
            if mode == 'stale-token': value['next_page_token'] = first['next_page_token']
            return value
        async with json_coordinator(mtls_material, [first, second, last]) as (config, calls):
            client = ot.CoordinatorClient(config, local_owner_id='journal-owner', clock=lambda: clock[0])
            assert await client.list_owned(ot.CallerAllowance(bound())) == ()
            assert 'page_token' not in calls[-1][0]
    run(scenario())


def test_coordinator_shared_budget_silence_and_cancellation(mtls_material):
    async def scenario():
        async def delay():
            await asyncio.sleep(.07)
            return wire('reserved')
        async with json_coordinator(mtls_material, [delay, delay]) as (config, calls):
            allowance = ot.CallerAllowance(bound(.11))
            client = coordinator(config)
            await client.status(wire('reserved')['lease_id'], allowance)
            with pytest.raises(ot.TransportError, match='operation_timeout'):
                await client.status(wire('reserved')['lease_id'], allowance)
            assert len(calls) == 2
            assert int(calls[1][1]['X-Deadline-Ms']) < 60
        async with json_coordinator(mtls_material, [delay]) as (config, calls):
            allowance = ot.CallerAllowance(bound(1))
            task = asyncio.create_task(coordinator(config).status(wire('reserved')['lease_id'], allowance))
            await asyncio.sleep(.02)
            allowance.cancelled.set()
            with pytest.raises(ot.TransportError, match='operation_timeout'):
                await task
            assert len(calls) <= 1
    run(scenario())


@pytest.mark.parametrize('vector', [v for v in _WIRE['invalid'] if v['type'] in ('LeaseStatus', 'ErrorBody', 'InventoryPage')], ids=lambda v: v['name'])
def test_coordinator_invalid_response_vectors(mtls_material, vector):
    async def scenario():
        lease = wire('reserved')['lease_id']
        status = 503 if vector['type'] == 'ErrorBody' else 200
        async with json_coordinator(mtls_material, [(status, vector['value'])]) as (config, _):
            client = coordinator(config)
            allowance = ot.CallerAllowance(bound())
            with pytest.raises(ot.TransportError) as error:
                if vector['type'] == 'InventoryPage': await client.list_owned(allowance)
                else: await client.status(lease, allowance)
            assert error.value.uncertain
    run(scenario())


def test_coordinator_create_is_once_and_validates_binding(mtls_material):
    async def scenario():
        lease = wire('reserved')['lease_id']
        reserve, create = wire('reserve-leg-min-ttl'), wire('deep-policy')
        create['service_exposures'] = []
        reserve['policy_digest'] = create['policy_digest']
        async with json_coordinator(mtls_material, [wire('reserved'), (503, b'SECRET dropped create')]) as (config, calls):
            client, allowance = coordinator(config), ot.CallerAllowance(bound())
            await client.reserve(lease, reserve, allowance)
            wrong = deepcopy(create)
            wrong['policy']['injected'] = True
            with pytest.raises(ot.TransportError, match='digest_mismatch'):
                await client.create(lease, wrong, allowance)
            with pytest.raises(ot.TransportError): await client.create(lease, create, allowance)
            with pytest.raises(ot.TransportError, match='not_repeatable'):
                await client.create(lease, create, allowance)
            assert len(calls) == 2
    run(scenario())


def test_coordinator_polling_consumes_original_allowance(mtls_material):
    async def scenario():
        async with json_coordinator(mtls_material, [wire('reserved')] * 50) as (config, calls):
            allowance = ot.CallerAllowance(bound(.12))
            with pytest.raises(ot.TransportError, match='operation_timeout'):
                await coordinator(config).poll_ready(wire('reserved')['lease_id'], allowance)
            assert 1 <= len(calls) <= 4
            assert all(int(c[1]['X-Deadline-Ms']) <= 120 for c in calls)
    run(scenario())


def test_coordinator_post_reserve_unavailable_is_uncertain(mtls_material):
    async def scenario():
        async with json_coordinator(mtls_material, [(503, wire('error-unavailable-recovering'))]) as (config, _):
            with pytest.raises(ot.TransportError, match='operation_timeout') as error:
                await coordinator(config).status(wire('reserved')['lease_id'], ot.CallerAllowance(bound()))
            assert error.value.uncertain
    run(scenario())


@pytest.mark.parametrize('flag', ['reserved', 'create_settled', 'ready', 'exec_claimed', 'fenced',
                                  'destruction_observed', 'cleanup_pending', 'barrier_confirmed', 'expired'])
def test_coordinator_every_historical_flag_cannot_regress(mtls_material, flag):
    async def scenario():
        previous = wire('destroyed')
        previous.update(state='expired', sandbox_id=GEN)
        previous['flags'] = {key: True for key in previous['flags']}
        later = deepcopy(previous)
        later['flags'][flag] = False
        if flag == 'expired': later['state'] = 'destroyed'
        async with json_coordinator(mtls_material, [previous, later]) as (config, _):
            client, allowance = coordinator(config), ot.CallerAllowance(bound())
            await client.status(previous['lease_id'], allowance)
            with pytest.raises(ot.TransportError, match='observation_regressed'):
                await client.status(previous['lease_id'], allowance)
            assert previous['lease_id'] in client.cleanup_obligations
    run(scenario())


def test_coordinator_typed_error_uses_code_even_with_advisory_http_status(mtls_material):
    async def scenario():
        async with json_coordinator(mtls_material, [wire('at_capacity', 'ErrorBody')]) as (config, _):
            with pytest.raises(ot.CoordinatorError, match='at_capacity') as error:
                await coordinator(config).reserve(wire('reserved')['lease_id'], wire('reserve-leg-min-ttl'),
                                                   ot.CallerAllowance(bound()))
            assert not error.value.uncertain and error.value.reason == 'pressure'
    run(scenario())


@pytest.mark.parametrize('fault,code', [
    ('workload', 'invalid_workload'), ('exposures', 'invalid_create'),
    ('policy', 'digest_mismatch'), ('image', 'digest_mismatch'),
    ('schema', 'invalid_create'),
])
def test_coordinator_upfront_refusal_never_reserves(mtls_material, fault, code):
    async def scenario():
        reserve, create = wire('reserve-leg-min-ttl'), wire('deep-policy')
        create['service_exposures'] = []
        reserve['policy_digest'] = create['policy_digest']
        if fault == 'workload': reserve['workload'] = 'pi-runner'
        if fault == 'exposures': create['service_exposures'] = wire('deep-policy')['service_exposures']
        if fault == 'policy': create['policy']['injected'] = True
        if fault == 'image': reserve['image_digest'] = 'sha256:' + 'f' * 64
        if fault == 'schema': del create['policy']
        async with json_coordinator(mtls_material, []) as (config, calls):
            client = coordinator(config)
            with pytest.raises(ot.TransportError, match=code) as error:
                await client.reserve(wire('reserved')['lease_id'], reserve,
                                     ot.CallerAllowance(bound()), create_body=create)
            assert not error.value.uncertain
            assert not calls and not client.cleanup_obligations
            assert not client._reserve_attempted and not client._bindings
    run(scenario())


@pytest.mark.parametrize('fault,code', [('exposures', 'invalid_create'), ('policy', 'digest_mismatch'),
                                       ('schema', 'invalid_create')])
def test_coordinator_post_reserve_local_refusal_is_uncertain(mtls_material, fault, code):
    async def scenario():
        reserve, create = wire('reserve-leg-min-ttl'), wire('deep-policy')
        create['service_exposures'] = []
        reserve['policy_digest'] = create['policy_digest']
        lease = wire('reserved')['lease_id']
        async with json_coordinator(mtls_material, [wire('reserved')]) as (config, calls):
            client, allowance = coordinator(config), ot.CallerAllowance(bound())
            await client.reserve(lease, reserve, allowance, create_body=create)
            if fault == 'exposures': create['service_exposures'] = wire('deep-policy')['service_exposures']
            if fault == 'policy': create['policy']['injected'] = True
            if fault == 'schema': del create['policy']
            with pytest.raises(ot.TransportError, match=code) as error:
                await client.create(lease, create, allowance)
            assert error.value.uncertain
            assert client.cleanup_obligations == {lease}
            assert len(calls) == 1
    run(scenario())


def test_coordinator_refused_port_reserve_holds_nothing(mtls_material):
    async def scenario():
        async with json_coordinator(mtls_material, []) as (config, calls):
            pass  # The local listener is closed: TCP connect is provably refused.
        client = coordinator(config)
        lease = wire('reserved')['lease_id']
        with pytest.raises(ot.TransportError, match='sandbox_placement_unreachable') as error:
            await client.reserve(lease, wire('reserve-leg-min-ttl'), ot.CallerAllowance(bound()))
        assert not error.value.uncertain
        assert not calls and not client.cleanup_obligations
        assert not client._reserve_attempted and not client._bindings and not client.poisoned_leases
    run(scenario())


def test_coordinator_lost_reserve_reply_keeps_obligation(mtls_material):
    async def scenario():
        async def lose_reply():
            raise ConnectionResetError
        async with json_coordinator(mtls_material, [lose_reply]) as (config, calls):
            client = coordinator(config)
            lease = wire('reserved')['lease_id']
            with pytest.raises(ot.TransportError, match='operation_timeout') as error:
                await client.reserve(lease, wire('reserve-leg-min-ttl'), ot.CallerAllowance(bound()))
            assert error.value.uncertain and len(calls) == 1
            assert client.cleanup_obligations == client._reserve_attempted == {lease}
    run(scenario())


@pytest.mark.parametrize('operation', ['create', 'renew', 'kill', 'status'])
def test_coordinator_held_lease_connect_failure_never_overflows(mtls_material, operation):
    async def scenario():
        reserve, create = wire('reserve-leg-min-ttl'), wire('deep-policy')
        create['service_exposures'] = []
        reserve['policy_digest'] = create['policy_digest']
        lease = wire('reserved')['lease_id']
        async with json_coordinator(mtls_material, [wire('reserved')]) as (config, calls):
            client = coordinator(config)
            await client.reserve(lease, reserve, ot.CallerAllowance(bound()), create_body=create)
        allowance = ot.CallerAllowance(bound())
        with pytest.raises(ot.TransportError, match='operation_timeout') as error:
            if operation == 'create': await client.create(lease, create, allowance)
            elif operation == 'renew': await client.renew(lease, 60, allowance)
            else: await getattr(client, operation)(lease, allowance)
        assert error.value.uncertain and len(calls) == 1
        assert client.cleanup_obligations == {lease}
        assert lease in client.poisoned_leases
    run(scenario())


@pytest.mark.parametrize('fault,code', [('lease', 'invalid_lease_identity'),
                                       ('body', 'invalid_coordinator_message')])
def test_coordinator_local_reserve_validation_holds_nothing(mtls_material, fault, code):
    async def scenario():
        lease, body = wire('reserved')['lease_id'], wire('reserve-leg-min-ttl')
        if fault == 'lease': lease = 'not-a-uuid'
        else: del body['workload']
        async with json_coordinator(mtls_material, []) as (config, calls):
            client = coordinator(config)
            with pytest.raises(ot.TransportError, match=code) as error:
                await client.reserve(lease, body, ot.CallerAllowance(bound()))
            assert not error.value.uncertain
            assert not calls and not client.cleanup_obligations
            assert not client._reserve_attempted and not client._create_attempted
            assert not client._bindings and not client._observations and not client.poisoned_leases
    run(scenario())


@pytest.mark.parametrize('held', [False, True])
def test_coordinator_refused_inventory_is_incomplete(mtls_material, held):
    async def scenario():
        lease = wire('reserved')['lease_id']
        async with json_coordinator(mtls_material, [wire('reserved')]) as (config, calls):
            client = coordinator(config)
            if held:
                await client.reserve(lease, wire('reserve-leg-min-ttl'), ot.CallerAllowance(bound()))
        before = (client.cleanup_obligations.copy(), client._reserve_attempted.copy(),
                  deepcopy(client._bindings), deepcopy(client._observations), client.poisoned_leases.copy())
        with pytest.raises(ot.TransportError, match='operation_timeout') as error:
            await client.list_owned(ot.CallerAllowance(bound()))
        assert error.value.uncertain
        assert len(calls) == int(held)
        assert before == (client.cleanup_obligations, client._reserve_attempted,
                          client._bindings, client._observations, client.poisoned_leases)
    run(scenario())


def test_coordinator_write_failure_is_after_send_boundary(mtls_material, monkeypatch):
    async def scenario():
        lease = wire('reserved')['lease_id']
        writes, drains, aborts = [], [], []
        class Writer:
            @property
            def transport(self): return self
            def write(self, data):
                writes.append(data)
                raise ConnectionResetError
            async def drain(self): drains.append(True)
            def abort(self): aborts.append(True)
        async def connect(*args, **kwargs): return None, Writer()
        async with json_coordinator(mtls_material, []) as (config, calls):
            client = coordinator(config)
            monkeypatch.setattr(ot.asyncio, 'open_connection', connect)
            with pytest.raises(ot.TransportError, match='operation_timeout') as error:
                await client.reserve(lease, wire('reserve-leg-min-ttl'), ot.CallerAllowance(bound()))
            assert error.value.uncertain
            assert len(writes) == 1 and not drains and aborts == [True] and not calls
            assert client._reserve_attempted == client.cleanup_obligations == {lease}
            assert client._bindings[lease] == wire('reserve-leg-min-ttl')
            assert client.poisoned_leases == {lease}
    run(scenario())
