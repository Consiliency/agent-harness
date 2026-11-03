"""Explicit mTLS identity and stock channel tests."""
import asyncio
from dataclasses import replace
import pytest
from phase_loop_runtime import openshell_channel as oc

from _openshell_channel_server import (
    json_coordinator, mtls_config, mtls_material as mtls_material, san_material as san_material,
    san_template as san_template,
)
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


@pytest.mark.parametrize('identity,host,accepted', [
    ('cn-only', '127.0.0.1', False), ('ip-san', '127.0.0.1', True),
    ('server', '127.0.0.1', False), ('cn-dns-only', 'localhost', False),
    ('wrong-ip-san', '127.0.0.1', False), ('no-extensions', '127.0.0.1', False),
    ('no-constraints', '127.0.0.1', False), ('ca-true', '127.0.0.1', False),
    ('no-eku', '127.0.0.1', False), ('client-eku', '127.0.0.1', False),
])
def test_stock_server_san_policy(san_material, identity, host, accepted):
    import shutil
    if identity != 'server':
        for suffix in ('pem', 'key'):
            shutil.copyfile(san_material / f'{identity}.{suffix}',
                            san_material / f'server.{suffix}')
    async def run():
        async with stock_server(san_material) as (config, p, state):
            config = replace(config, endpoint=config.endpoint.replace('localhost', host))
            async def dispatch():
                async with oc.stock_exec_channel(config, p) as channel:
                    if not accepted:
                        pytest.fail('server identity accepted before dispatch')
                    session = channel.bind_lease(wire('reserved')['lease_id'],
                        '11111111-2222-4333-8444-555555555555', local_owner_id='journal-owner')
                    await session.execute(p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker']),
                        ot.CallerAllowance(bound(1)), attempt=1,
                        output_cap_bytes=100, message_cap=10)
            if accepted:
                await dispatch()
                assert len(state.calls) == 1
            else:
                with pytest.raises(ot.TransportError) as error:
                    await dispatch()
                assert str(error.value) == 'channel_peer_verification_failed'
                assert error.value.uncertain is False
                assert not state.calls
    asyncio.run(run())


def test_stock_channel_pins_validated_leaf(san_material, monkeypatch):
    import grpc
    import hashlib
    import shutil
    import ssl
    async def run():
        for suffix in ('pem', 'key'):
            shutil.copyfile(san_material / f'ip-san.{suffix}', san_material / f'server.{suffix}')
        async with stock_server(san_material) as (config, p, original_state):
            for suffix in ('pem', 'key'):
                shutil.copyfile(san_material / f'other-ip-san.{suffix}', san_material / f'server.{suffix}')
            async with stock_server(san_material) as (other, _, other_state):
                secure_channel = grpc.aio.secure_channel
                def redirected(target, credentials, *, options):
                    return secure_channel(other.endpoint.removeprefix('https://').replace(
                        'localhost', '127.0.0.1'), credentials, options=options)
                monkeypatch.setattr(grpc.aio, 'secure_channel', redirected)
                config = replace(config, endpoint=config.endpoint.replace('localhost', '127.0.0.1'))
                with pytest.raises(ot.TransportError):
                    async with oc.stock_exec_channel(config, p):
                        pytest.fail('different leaf accepted')
                assert not original_state.calls and not other_state.calls
        # The successful path records the verified DER fingerprint.
        monkeypatch.setattr(grpc.aio, 'secure_channel', secure_channel)
        async with stock_server(san_material) as (config, p, _):
            config = replace(config, endpoint=config.endpoint.replace('localhost', '127.0.0.1'))
            async with oc.stock_exec_channel(config, p) as channel:
                der = ssl.PEM_cert_to_DER_cert((san_material / 'server.pem').read_text())
                assert channel.peer_certificate_sha256 == hashlib.sha256(der).hexdigest()
    asyncio.run(run())



def test_stock_leaf_without_constraints_cannot_authorize_child(san_material, monkeypatch):
    import grpc
    import shutil
    async def run():
        for suffix in ('pem', 'key'):
            shutil.copyfile(san_material / f'no-constraints.{suffix}',
                            san_material / f'server.{suffix}')
        async with stock_server(san_material) as (config, p, parent_state):
            for suffix in ('pem', 'key'):
                shutil.copyfile(san_material / f'child.{suffix}',
                                san_material / f'server.{suffix}')
            async with stock_server(san_material) as (child, _, child_state):
                secure_channel = grpc.aio.secure_channel
                def redirected(target, credentials, *, options):
                    return secure_channel(child.endpoint.removeprefix('https://').replace(
                        'localhost', '127.0.0.1'), credentials, options=options)
                monkeypatch.setattr(grpc.aio, 'secure_channel', redirected)
                config = replace(config, endpoint=config.endpoint.replace('localhost', '127.0.0.1'))
                with pytest.raises(ot.TransportError) as error:
                    async with oc.stock_exec_channel(config, p) as channel:
                        session = channel.bind_lease(wire('reserved')['lease_id'],
                            '11111111-2222-4333-8444-555555555555', local_owner_id='journal-owner')
                        await session.execute(
                            p.ExecSandboxRequest(workspace_scope={'workspace': 'offline'}, command=['worker']),
                            ot.CallerAllowance(bound(1)), attempt=1,
                            output_cap_bytes=100, message_cap=10)
                assert error.value.code == 'channel_peer_verification_failed'
                assert error.value.uncertain is False
                assert not parent_state.calls and not child_state.calls
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['refused', 'timeout'])
def test_stock_predial_connect_failures_are_certain(mtls_material, monkeypatch, failure):
    async def run():
        async with stock_server(mtls_material) as (config, p, state):
            if failure == 'timeout':
                async def stalled(*args, **kwargs):
                    await asyncio.Event().wait()
                monkeypatch.setattr(oc.asyncio, 'open_connection', stalled)
                config = replace(config, connect_timeout_s=0.01)
            else:
                listener = await asyncio.start_server(lambda r, w: w.close(), '127.0.0.1', 0)
                port = listener.sockets[0].getsockname()[1]
                listener.close()
                await listener.wait_closed()
                config = replace(config, endpoint=f'https://127.0.0.1:{port}')
            with pytest.raises(ot.TransportError) as error:
                async with oc.stock_exec_channel(config, p):
                    pytest.fail('failed dial yielded a channel')
            assert error.value.code == 'sandbox_placement_unreachable'
            assert error.value.uncertain is False
            assert not state.calls
            assert '127.0.0.1' not in str(error.value)
    asyncio.run(run())
