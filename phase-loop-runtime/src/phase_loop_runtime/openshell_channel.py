"""Unregistered explicit mTLS channels."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import ipaddress
import math
import os
import re
import ssl
from urllib.parse import urlsplit

from .openshell_transport import TransportError


def _positive_timeout(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise TransportError("invalid_channel_timeout")


#: The certificate OU each placement client presents (``x-identity-inventories``).
CLIENT_CERTIFICATE_OU = {"agent-harness": "agent-harness", "agent-toolkit": "agent-toolkit"}


def certificate_ou_for(client: str) -> str:
    """The OU a placement client's certificate must carry; unknown clients refuse."""
    try:
        return CLIENT_CERTIFICATE_OU[client]
    except (KeyError, TypeError):
        raise TransportError("invalid_mtls_identity") from None


@dataclass(frozen=True)
class MTLSConfig:
    """Explicit coordinator/proxy identity; local journal ownership is separate.

    No settings, ambient roots, tokens, proxies or authority overrides are read.
    Certificates and keys are caller supplied, never included in diagnostics.
    ``client_ou`` is the selected placement client's OU: agent-harness seats keep
    OU=agent-harness and every Pi target uses OU=agent-toolkit.
    """

    endpoint: str
    owner_cn: str
    local_owner_id: str
    ca_pem: bytes = field(repr=False)
    client_cert_pem: bytes = field(repr=False)
    client_key_pem: bytes = field(repr=False)
    receive_limit_bytes: int
    connect_timeout_s: float
    client_ou: str = "agent-harness"

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
        if self.client_ou not in CLIENT_CERTIFICATE_OU.values():
            raise TransportError('invalid_mtls_identity')
        if type(self.receive_limit_bytes) is not int or not 0 < self.receive_limit_bytes <= 2**31 - 1:
            raise TransportError('invalid_receive_limit')
        _positive_timeout(self.connect_timeout_s)
        if not all(type(v) is bytes and v for v in
                   (self.ca_pem, self.client_cert_pem, self.client_key_pem)):
            raise TransportError('invalid_mtls_credential')
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.verify_mode = ssl.CERT_REQUIRED
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
                if cns != [self.owner_cn] or ous != [self.client_ou]:
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
    target, context = config.validate(config.local_owner_id)
    url = urlsplit(config.endpoint)
    connect_deadline = asyncio.get_running_loop().time() + config.connect_timeout_s
    writer = None
    # uncertain=False below is correct only because this channel opens before
    # any lease exists. A caller opening it after create must treat failures
    # as uncertain, even though this handshake sends no ExecSandbox.
    try:
        async with asyncio.timeout_at(connect_deadline):
            _, writer = await asyncio.open_connection(
                url.hostname, url.port or 443, ssl=context,
                server_hostname=url.hostname)
            leaf = writer.get_extra_info('ssl_object').getpeercert(binary_form=True)
    except ssl.SSLCertVerificationError:
        raise TransportError('channel_peer_verification_failed', uncertain=False) from None
    except (OSError, TimeoutError):
        raise TransportError('sandbox_placement_unreachable', uncertain=False) from None
    finally:
        if writer is not None:
            writer.close()
            # TLS shutdown is best effort and must not extend the dial deadline.
    leaf_sha256 = hashlib.sha256(leaf).hexdigest()
    # grpcio 1.78 exposes no client peer-cert hook and BoringSSL does not
    # enforce basicConstraints on a trust anchor (measured in the known-
    # limitation test). Trust only the SAN-validated leaf, not its issuing CA.
    # A different leaf from that CA or an unrelated certificate is refused.
    # Signing a child accepted by this anchor requires the leaf's private key:
    # the residual is server-key compromise, which TLS cannot defend against.
    pinned_root = ssl.DER_cert_to_PEM_cert(leaf).encode('ascii')
    import grpc
    credentials = grpc.ssl_channel_credentials(root_certificates=pinned_root,
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
    client.peer_certificate_sha256 = leaf_sha256
    try:
        try:
            async with asyncio.timeout_at(connect_deadline):
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
