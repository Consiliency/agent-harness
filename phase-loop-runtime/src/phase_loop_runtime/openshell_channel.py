"""Unregistered channels: explicit mTLS plus the retained legacy bearer adapter."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import ipaddress
import math
import os
import re
import ssl
from urllib.parse import urlsplit

from . import placement_lease
from .openshell_transport import TransportError


def _positive_timeout(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise TransportError("invalid_channel_timeout")


# Legacy: removed by OSCOORD2 SL-2; callers migrate there
@dataclass(frozen=True)
class ChannelConfig:
    """Explicit trust and resolved limits; no credential discovery or defaults.

    The caller resolves operational settings through the existing settings loader.
    No receive-limit or OpenShell trust setting currently exists there: inject it.
    """

    endpoint: str
    workspace: str
    owner_id: str
    ca_pem: bytes = field(repr=False)
    bearer_token: str = field(repr=False)
    receive_limit_bytes: int
    connect_timeout_s: float

    def target(self):
        try:
            if (type(self.endpoint) is not str or not self.endpoint.startswith("https://")
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in self.endpoint)):
                raise ValueError
            url = urlsplit(self.endpoint)
            host = url.hostname
            if (not host or url.username is not None or url.password is not None
                    or url.path not in ("", "/") or url.query or url.fragment
                    or "?" in self.endpoint or "#" in self.endpoint
                    or "%" in host or url.netloc.endswith(":")):
                raise ValueError
            if ":" in host:
                ipaddress.IPv6Address(host)
                host = f"[{host}]"
            elif not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                raise ValueError
            elif any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                     for label in host.split(".")) or len(host) > 253:
                raise ValueError
            port = url.port
            authority = host if port is None else f"{host}:{port}"
            if port == 0 or url.netloc.lower() != authority.lower():
                raise ValueError
            return f"{host}:{port if port is not None else 443}"
        except (ValueError, TypeError, AttributeError):
            raise TransportError("invalid_channel_endpoint") from None

    def validate(self):
        target = self.target()
        if not all(type(v) is str and v and v.strip() == v
                   for v in (self.workspace, self.owner_id)):
            raise TransportError("invalid_scope")
        if (type(self.receive_limit_bytes) is not int
                or not 0 < self.receive_limit_bytes <= 2**31 - 1):
            raise TransportError("invalid_receive_limit")
        _positive_timeout(self.connect_timeout_s)
        if (type(self.bearer_token) is not str
                or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", self.bearer_token)):
            raise TransportError("invalid_channel_credential")
        try:
            if type(self.ca_pem) is not bytes or not self.ca_pem:
                raise ValueError
            # An empty/invalid input must never select gRPC's ambient root store.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cadata=self.ca_pem.decode("ascii"))
        except (ValueError, UnicodeError, ssl.SSLError):
            raise TransportError("invalid_channel_trust") from None
        if self.owner_id != placement_lease.owner_id():
            raise TransportError("owner_workspace_refused")
        return target


# Legacy: removed by OSCOORD2 SL-2; callers migrate there
class _ScopedStub:
    def __init__(self, stub, config):
        self._stub = stub
        self._workspace = config.workspace
        self._owner = config.owner_id
        self._loop = asyncio.get_running_loop()
        self._pid = os.getpid()
        self._closed = False

    def _check(self, request, timeout):
        if self._pid != os.getpid() or self._closed:
            raise TransportError("invalid_channel_context")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise TransportError("invalid_channel_context") from None
        if loop is not self._loop:
            raise TransportError("invalid_channel_context")
        _positive_timeout(timeout)
        if (request.owner_id != self._owner or request.workspace_scope.workspace != self._workspace
                or placement_lease.owner_id() != self._owner):
            raise TransportError("owner_workspace_refused")

    def ControlCancellationLease(self, request, *, timeout):
        self._check(request, timeout)
        return self._stub.ControlCancellationLease(request, timeout=timeout, wait_for_ready=False)

    def ExecCancellationLease(self, request, *, timeout):
        self._check(request, timeout)
        return self._stub.ExecCancellationLease(request, timeout=timeout, wait_for_ready=False)

    def SourceCancellationLease(self, request, *, timeout):
        self._check(request, timeout)
        return self._stub.SourceCancellationLease(request, timeout=timeout, wait_for_ready=False)


@asynccontextmanager
# Legacy: removed by OSCOORD2 SL-2; callers migrate there
async def authenticated_channel(config: ChannelConfig, service):
    """Yield a scoped generated stub on this running loop, then cancel/close it.

    `service` is the caller's pinned generated openshell_pb2_grpc module. TLS
    readiness authenticates the endpoint only. The server must authenticate the
    bearer, authorize workspace access and match prior dedicated-workspace
    enrollment on every RPC. This factory never enrolls or refreshes credentials.
    """
    target = config.validate()
    import grpc

    credentials = grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(root_certificates=config.ca_pem),
        grpc.access_token_call_credentials(config.bearer_token),
    )
    channel = grpc.aio.secure_channel(target, credentials, options=(
        ("grpc.enable_retries", 0),
        ("grpc.service_config_disable_resolution", 1),
        ("grpc.max_receive_message_length", config.receive_limit_bytes),
        ("grpc.enable_http_proxy", 0),
    ))
    stub = None
    try:
        try:
            async with asyncio.timeout(config.connect_timeout_s):
                await channel.channel_ready()
        except TimeoutError:
            raise TransportError("channel_connect_timeout") from None
        stub = _ScopedStub(service.OpenShellStub(channel), config)
        yield stub
    finally:
        if stub is not None:
            stub._closed = True
        # No graceful drain: close immediately cancels outstanding calls. The
        # caller must keep this loop alive until context exit finishes.
        await channel.close(grace=None)


@dataclass(frozen=True)
class MTLSConfig:
    """Explicit coordinator/proxy identity; local journal ownership is separate.

    No settings, ambient roots, tokens, proxies or authority overrides are read.
    Certificates and keys are caller supplied, never included in diagnostics.
    """

    endpoint: str
    owner_cn: str
    local_owner_id: str
    ca_pem: bytes = field(repr=False)
    client_cert_pem: bytes = field(repr=False)
    client_key_pem: bytes = field(repr=False)
    receive_limit_bytes: int
    connect_timeout_s: float

    def target(self):
        try:
            if (type(self.endpoint) is not str or not self.endpoint.startswith("https://")
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in self.endpoint)):
                raise ValueError
            url = urlsplit(self.endpoint)
            host = url.hostname
            if (not host or url.username is not None or url.password is not None
                    or url.path not in ("", "/") or url.query or url.fragment
                    or "?" in self.endpoint or "#" in self.endpoint
                    or "%" in host or url.netloc.endswith(":")):
                raise ValueError
            if ":" in host:
                ipaddress.IPv6Address(host)
                host = f"[{host}]"
            elif not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                raise ValueError
            elif any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                     for label in host.split(".")) or len(host) > 253:
                raise ValueError
            port = url.port
            authority = host if port is None else f"{host}:{port}"
            if port == 0 or url.netloc.lower() != authority.lower():
                raise ValueError
            return f"{host}:{port if port is not None else 443}"
        except (ValueError, TypeError, AttributeError):
            raise TransportError("invalid_channel_endpoint") from None


    def validate(self, local_owner_id):
        from pathlib import Path
        import tempfile
        target = self.target()
        if (not all(type(v) is str and v and v.strip() == v
                    for v in (self.owner_cn, self.local_owner_id))
                or local_owner_id != self.local_owner_id):
            raise TransportError('invalid_local_owner_binding')
        if type(self.receive_limit_bytes) is not int or not 0 < self.receive_limit_bytes <= 2**31 - 1:
            raise TransportError('invalid_receive_limit')
        _positive_timeout(self.connect_timeout_s)
        if not all(type(v) is bytes and v for v in
                   (self.ca_pem, self.client_cert_pem, self.client_key_pem)):
            raise TransportError('invalid_mtls_credential')
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.hostname_checks_common_name = False
            context.load_verify_locations(cadata=self.ca_pem.decode('ascii'))
            # ssl requires paths to load a key. Private temporary files are never
            # discovered or retained; TemporaryDirectory follows caller TMPDIR.
            with tempfile.TemporaryDirectory(prefix='openshell-mtls-') as temp:
                cert, key = Path(temp) / 'client.pem', Path(temp) / 'client.key'
                for path, data in ((cert, self.client_cert_pem), (key, self.client_key_pem)):
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'wb') as handle:
                        handle.write(data)
                identity = ssl._ssl._test_decode_cert(str(cert))
                subject = [item for rdn in identity['subject'] for item in rdn]
                cns = [v for k, v in subject if k == 'commonName']
                ous = [v for k, v in subject if k == 'organizationalUnitName']
                if cns != [self.owner_cn] or ous != ['agent-harness']:
                    raise TransportError('invalid_mtls_identity')
                # Never let OpenSSL prompt for an ambient key passphrase.
                context.load_cert_chain(cert, key, password=lambda: b'')
            return target, context
        except TransportError:
            raise
        except (OSError, ValueError, UnicodeError, ssl.SSLError):
            raise TransportError('invalid_mtls_credential') from None


@asynccontextmanager
async def stock_exec_channel(config: MTLSConfig, proto):
    """Stock ExecSandbox only. TLS readiness grants no lifecycle authority."""
    from .openshell_transport import StockExecChannel
    target, _ = config.validate(config.local_owner_id)
    import grpc
    credentials = grpc.ssl_channel_credentials(root_certificates=config.ca_pem,
        private_key=config.client_key_pem, certificate_chain=config.client_cert_pem)
    channel = grpc.aio.secure_channel(target, credentials, options=(
        ('grpc.enable_retries', 0),
        ('grpc.service_config_disable_resolution', 1),
        ('grpc.service_config', '{}'),
        ('grpc.max_receive_message_length', config.receive_limit_bytes),
        ('grpc.max_send_message_length', 4 * 1024 * 1024),
        ('grpc.enable_http_proxy', 0),
    ))
    client = StockExecChannel(channel, proto, config.local_owner_id)
    try:
        try:
            async with asyncio.timeout(config.connect_timeout_s):
                await channel.channel_ready()
        except Exception:
            raise TransportError('channel_connect_timeout', uncertain=True) from None
        yield client
    finally:
        client.close()
        try:
            async with asyncio.timeout(min(config.connect_timeout_s, 0.5)):
                await channel.close(grace=None)
        except TimeoutError:
            raise TransportError('channel_close_timeout', uncertain=True) from None
        except Exception:
            raise TransportError('channel_close_failed', uncertain=True) from None
