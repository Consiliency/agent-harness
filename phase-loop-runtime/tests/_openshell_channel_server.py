"""Stock OpenShell v0.1.4 exec fixtures for offline tests: descriptor and bindings only."""

import asyncio
import json
# NVIDIA/OpenShell v0.1.4, commit 5a7728c304b5528e954e9ae900cf21f84e1a12b1.
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
# protoc (grpcio-tools 1.78.0) --include_imports --descriptor_set_out=stock.pb
# Generated from stock proto/openshell.proto and proto/datamodel.proto; only the
# ExecSandbox method/messages and WorkspaceSelector are retained, unmodified.
# The reserved field 5, request_id field 11 and timeout field 105 are preserved.
STOCK_EXEC_DESCRIPTOR = "CtUBCg9kYXRhbW9kZWwucHJvdG8SFm9wZW5zaGVsbC5kYXRhbW9kZWwudjEikAEKEVdvcmtzcGFjZVNlbGVjdG9yEh4KCXdvcmtzcGFjZRgBIAEoCUgAUgl3b3Jrc3BhY2USTgoOYWxsX3dvcmtzcGFjZXMYAiABKAsyJS5vcGVuc2hlbGwuZGF0YW1vZGVsLnYxLkFsbFdvcmtzcGFjZXNIAFINYWxsV29ya3NwYWNlc0ILCglzZWxlY3Rpb24iDwoNQWxsV29ya3NwYWNlc2IGcHJvdG8zCusICg9vcGVuc2hlbGwucHJvdG8SDG9wZW5zaGVsbC52MRoPZGF0YW1vZGVsLnByb3RvGh5nb29nbGUvcHJvdG9idWYvZHVyYXRpb24ucHJvdG8ivwQKEkV4ZWNTYW5kYm94UmVxdWVzdBJSCg93b3Jrc3BhY2Vfc2NvcGUYDCABKAsyKS5vcGVuc2hlbGwuZGF0YW1vZGVsLnYxLldvcmtzcGFjZVNlbGVjdG9yUg53b3Jrc3BhY2VTY29wZRIYCgdzYW5kYm94GAEgASgJUgdzYW5kYm94EhgKB2NvbW1hbmQYAiADKAlSB2NvbW1hbmQSGAoHd29ya2RpchgDIAEoCVIHd29ya2RpchJTCgtlbnZpcm9ubWVudBgEIAMoCzIxLm9wZW5zaGVsbC52MS5FeGVjU2FuZGJveFJlcXVlc3QuRW52aXJvbm1lbnRFbnRyeVILZW52aXJvbm1lbnQSRgoRZXhlY3V0aW9uX3RpbWVvdXQYaSABKAsyGS5nb29nbGUucHJvdG9idWYuRHVyYXRpb25SEGV4ZWN1dGlvblRpbWVvdXQSFAoFc3RkaW4YBiABKAxSBXN0ZGluEhAKA3R0eRgHIAEoCFIDdHR5EhIKBGNvbHMYCCABKA1SBGNvbHMSEgoEcm93cxgJIAEoDVIEcm93cxIkCg5ub19sb2dpbl9zaGVsbBgKIAEoCFIMbm9Mb2dpblNoZWxsEh0KCnJlcXVlc3RfaWQYCyABKAlSCXJlcXVlc3RJZBo+ChBFbnZpcm9ubWVudEVudHJ5EhAKA2tleRgBIAEoCVIDa2V5EhQKBXZhbHVlGAIgASgJUgV2YWx1ZToCOAFKBAgFEAZSD3RpbWVvdXRfc2Vjb25kcyInChFFeGVjU2FuZGJveFN0ZG91dBISCgRkYXRhGAEgASgMUgRkYXRhIicKEUV4ZWNTYW5kYm94U3RkZXJyEhIKBGRhdGEYASABKAxSBGRhdGEiLgoPRXhlY1NhbmRib3hFeGl0EhsKCWV4aXRfY29kZRgBIAEoBVIIZXhpdENvZGUiyAEKEEV4ZWNTYW5kYm94RXZlbnQSOQoGc3Rkb3V0GAEgASgLMh8ub3BlbnNoZWxsLnYxLkV4ZWNTYW5kYm94U3Rkb3V0SABSBnN0ZG91dBI5CgZzdGRlcnIYAiABKAsyHy5vcGVuc2hlbGwudjEuRXhlY1NhbmRib3hTdGRlcnJIAFIGc3RkZXJyEjMKBGV4aXQYAyABKAsyHS5vcGVuc2hlbGwudjEuRXhlY1NhbmRib3hFeGl0SABSBGV4aXRCCQoHcGF5bG9hZDKBAQoJT3BlblNoZWxsEnQKC0V4ZWNTYW5kYm94EiAub3BlbnNoZWxsLnYxLkV4ZWNTYW5kYm94UmVxdWVzdBoeLm9wZW5zaGVsbC52MS5FeGVjU2FuZGJveEV2ZW50IiGCtRgdCgZiZWFyZXISBHVzZXIiDXNhbmRib3g6d3JpdGUwAWIGcHJvdG8z"


def stock_bindings():
    import base64
    from google.protobuf import descriptor_pb2, descriptor_pool, duration_pb2, message_factory
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(duration_pb2.DESCRIPTOR.serialized_pb)
    files = descriptor_pb2.FileDescriptorSet.FromString(base64.b64decode(STOCK_EXEC_DESCRIPTOR))
    for file in files.file:
        pool.Add(file)
    return SimpleNamespace(**{name: message_factory.GetMessageClass(
        pool.FindMessageTypeByName('openshell.v1.' + name)) for name in
        ('ExecSandboxRequest', 'ExecSandboxEvent')})


# Offline test helpers shared by the new coordinator and stock channel suites.
import ssl
import subprocess
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture(scope='module')
def mtls_material(tmp_path_factory):
    directory = tmp_path_factory.mktemp('coordinator-certs')
    def command(*args):
        subprocess.run(['openssl', *args], cwd=directory, check=True,
                       capture_output=True, timeout=15)
    for ca in ('ca', 'other'):
        command('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-subj', '/CN=offline-' + ca, '-keyout', ca + '.key', '-out', ca + '.pem')
    for name, subject, extension, issuer in (
        ('server', '/CN=unused', 'subjectAltName=DNS:localhost\nextendedKeyUsage=serverAuth', 'ca'),
        ('client', '/CN=cert-owner/OU=agent-harness', 'extendedKeyUsage=clientAuth', 'ca'),
        ('wrong-ou', '/CN=cert-owner/OU=agent-toolkit', 'extendedKeyUsage=clientAuth', 'ca'),
        ('untrusted', '/CN=cert-owner/OU=agent-harness', 'extendedKeyUsage=clientAuth', 'other'),
    ):
        command('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', subject,
                '-keyout', name + '.key', '-out', name + '.csr')
        (directory / 'extensions').write_text(extension + '\n')
        command('x509', '-req', '-in', name + '.csr', '-CA', issuer + '.pem',
                '-CAkey', issuer + '.key', '-CAcreateserial', '-days', '1',
                '-extfile', 'extensions', '-out', name + '.pem')
    command('pkey', '-in', 'client.key', '-aes-256-cbc', '-passout',
            'pass:synthetic', '-out', 'encrypted.key')
    return directory


def mtls_config(material, endpoint='https://localhost:443'):
    from phase_loop_runtime.openshell_channel import MTLSConfig
    return MTLSConfig(endpoint=endpoint, owner_cn='cert-owner', local_owner_id='journal-owner',
                      ca_pem=(material / 'ca.pem').read_bytes(),
                      client_cert_pem=(material / 'client.pem').read_bytes(),
                      client_key_pem=(material / 'client.key').read_bytes(),
                      receive_limit_bytes=65536, connect_timeout_s=0.5)


@asynccontextmanager
async def json_coordinator(material, replies):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(material / 'server.pem', material / 'server.key')
    context.load_verify_locations(material / 'ca.pem')
    context.verify_mode = ssl.CERT_REQUIRED
    calls, tasks = [], set()
    async def receive(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            head = await reader.readuntil(b'\r\n\r\n')
            lines = head.decode().split('\r\n')
            headers = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
            body = await reader.readexactly(int(headers.get('Content-Length', 0)))
            calls.append((lines[0], headers, json.loads(body) if body else None))
            response = replies.pop(0)
            if callable(response):
                response = await response()
            status, value = response if isinstance(response, tuple) else (200, response)
            wire = value if isinstance(value, bytes) else json.dumps(value).encode()
            writer.write(f'HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {len(wire)}\r\nConnection: close\r\n\r\n'.encode() + wire)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            tasks.discard(task)
    server = await asyncio.start_server(receive, '127.0.0.1', 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    try:
        yield mtls_config(material, f'https://localhost:{port}'), calls
    finally:
        server.close()
        await server.wait_closed()
        for task in tuple(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
