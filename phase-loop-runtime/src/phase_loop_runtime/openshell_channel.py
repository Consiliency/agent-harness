"""Private, unregistered HTTPS/bearer channel; no enrollment or launch authority."""

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
