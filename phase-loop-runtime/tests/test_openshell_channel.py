"""Explicit mTLS identity and stock channel tests."""
import asyncio
from dataclasses import replace
import pytest
from phase_loop_runtime import openshell_channel as oc

from _openshell_channel_server import json_coordinator, mtls_config, mtls_material as mtls_material
from phase_loop_runtime import openshell_transport as ot
from test_openshell_transport import bound, wire
from test_openshell_transport_grpc import stock_server


@pytest.mark.parametrize('fault', ['wrong-ca', 'wrong-san', 'wrong-ou', 'wrong-cn', 'failed-client-auth', 'wrong-key', 'encrypted-key'])
def test_mtls_identity_and_endpoint_checks_fail_closed(mtls_material, fault):
    async def run():
        async with json_coordinator(mtls_material, [wire('reserved')]) as (config, calls):
            if fault == 'wrong-ca': config = replace(config, ca_pem=(mtls_material / 'other.pem').read_bytes())
            if fault == 'wrong-san': config = replace(config, endpoint=config.endpoint.replace('localhost', '127.0.0.1'))
            if fault == 'wrong-ou': config = replace(config, client_cert_pem=(mtls_material / 'wrong-ou.pem').read_bytes(), client_key_pem=(mtls_material / 'wrong-ou.key').read_bytes())
            if fault == 'wrong-cn': config = replace(config, owner_cn='another-owner')
            if fault == 'failed-client-auth': config = replace(config, client_cert_pem=(mtls_material / 'untrusted.pem').read_bytes(), client_key_pem=(mtls_material / 'untrusted.key').read_bytes())
            if fault == 'wrong-key': config = replace(config, client_key_pem=(mtls_material / 'wrong-ou.key').read_bytes())
            if fault == 'encrypted-key': config = replace(config, client_key_pem=(mtls_material / 'encrypted.key').read_bytes())
            with pytest.raises(ot.TransportError) as error:
                await ot.CoordinatorClient(config, local_owner_id='journal-owner').status(
                    wire('reserved')['lease_id'], ot.CallerAllowance(bound(.2)))
            assert not calls
            assert 'PRIVATE KEY' not in str(error.value) and 'cert-owner' not in str(error.value)
    asyncio.run(run())


def test_mtls_local_owner_binding_is_explicit(mtls_material):
    config = mtls_config(mtls_material)
    with pytest.raises(ot.TransportError, match='local_owner'):
        ot.CoordinatorClient(config, local_owner_id=config.owner_cn)
    assert ot.CoordinatorClient(config, local_owner_id='journal-owner').local_owner_id == 'journal-owner'


@pytest.mark.parametrize('fault', ['wrong-ca', 'wrong-san', 'failed-client-auth'])
def test_stock_mtls_rejects_untrusted_peers(mtls_material, fault):
    async def run():
        async with stock_server(mtls_material) as (config, p, state):
            if fault == 'wrong-ca': config = replace(config, ca_pem=(mtls_material / 'other.pem').read_bytes())
            if fault == 'wrong-san': config = replace(config, endpoint=config.endpoint.replace('localhost', '127.0.0.1'))
            if fault == 'failed-client-auth': config = replace(config, client_cert_pem=(mtls_material / 'untrusted.pem').read_bytes(), client_key_pem=(mtls_material / 'untrusted.key').read_bytes())
            with pytest.raises(ot.TransportError):
                async with oc.stock_exec_channel(config, p):
                    pytest.fail('untrusted connection accepted')
            assert not state.calls
    asyncio.run(run())


def test_stock_channel_close_is_bounded(mtls_material):
    async def run():
        async with stock_server(mtls_material, mode='silence') as (config, p, state):
            started = asyncio.get_running_loop().time()
            async with oc.stock_exec_channel(config, p) as channel:
                session = channel.bind_lease(wire('reserved')['lease_id'], '11111111-2222-4333-8444-555555555555', local_owner_id='journal-owner')
                task = asyncio.create_task(session.execute(p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker']),
                    ot.CallerAllowance(bound(5)), attempt=1, output_cap_bytes=100, message_cap=10))
                await asyncio.wait_for(state.entered.wait(), 1)
            with pytest.raises((ot.TransportError, asyncio.CancelledError)):
                await asyncio.wait_for(task, .5)
            assert asyncio.get_running_loop().time() - started < 1.5
    asyncio.run(run())
