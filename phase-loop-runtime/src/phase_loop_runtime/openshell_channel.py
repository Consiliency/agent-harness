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
                if cns != [self.owner_cn] or ous != ['agent-harness']:
                    raise TransportError('invalid_mtls_identity')
                # Never let OpenSSL prompt for an ambient key passphrase.
                context.load_cert_chain(cert, key, password=lambda: b'')
            return target, context
        except TransportError:
            raise
        except (OSError, ValueError, UnicodeError, ssl.SSLError):
            raise TransportError('invalid_mtls_credential') from None


def _der_fields(data):
    """Read definite-length DER fields from an already TLS-validated certificate.

    Only the extension envelope is decoded here; OpenSSL handles certificate,
    signature and hostname validation. No optional ASN.1 dependency is needed.
    """
    offset = 0
    while offset < len(data):
        tag, size = data[offset:offset + 2]
        offset += 2
        if size & 0x80:
            width = size & 0x7f
            if not 1 <= width <= 4 or offset + width > len(data):
                raise ValueError
            encoded = data[offset:offset + width]
            size = int.from_bytes(encoded)
            if encoded[0] == 0 or size < 128:
                raise ValueError
            offset += width
        end = offset + size
        if end > len(data):
            raise ValueError
        yield tag, data[offset:end]
        offset = end


def _server_leaf_extensions(leaf):
    """Require an explicit non-CA leaf and explicit TLS server authentication."""
    try:
        ((tag, certificate),) = _der_fields(leaf)
        if tag != 0x30:
            raise ValueError
        (tag, tbs), *_ = _der_fields(certificate)
        if tag != 0x30:
            raise ValueError
        ((_, wrapper),) = [(tag, value) for tag, value in _der_fields(tbs) if tag == 0xa3]
        ((tag, extensions),) = _der_fields(wrapper)
        if tag != 0x30:
            raise ValueError
        values = {}
        for tag, extension in _der_fields(extensions):
            if tag != 0x30:
                raise ValueError
            fields = list(_der_fields(extension))
            oid_tag, oid = fields.pop(0)
            if fields and fields[0][0] == 0x01:  # optional critical flag
                fields.pop(0)
            ((value_tag, value),) = fields
            if oid_tag != 0x06 or value_tag != 0x04 or oid in values:
                raise ValueError
            values[oid] = value
        # basicConstraints: absent cA inside the *present* SEQUENCE means FALSE.
        # An absent extension is unsafe as a gRPC trust anchor and is refused.
        constraints = values.get(b'\x55\x1d\x13')
        if constraints not in (b'\x30\x00', b'\x30\x03\x01\x01\x00'):
            raise ValueError
        ((tag, purposes),) = _der_fields(values[b'\x55\x1d\x25'])
        if tag != 0x30:
            raise ValueError
        usages = list(_der_fields(purposes))
        if (any(tag != 0x06 for tag, _ in usages)
                or (0x06, b'\x2b\x06\x01\x05\x05\x07\x03\x01') not in usages):
            raise ValueError
    except (ValueError, KeyError, IndexError):
        raise TransportError('channel_peer_verification_failed', uncertain=False) from None


@asynccontextmanager
async def stock_exec_channel(config: MTLSConfig, proto):
    """Stock ExecSandbox only. TLS readiness grants no lifecycle authority."""
    from .openshell_transport import StockExecChannel
    target, context = config.validate(config.local_owner_id)
    url = urlsplit(config.endpoint)
    connect_deadline = asyncio.get_running_loop().time() + config.connect_timeout_s
    writer = None
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
    _server_leaf_extensions(leaf)
    leaf_sha256 = hashlib.sha256(leaf).hexdigest()
    # grpcio 1.78 exposes neither the client peer certificate nor a Python
    # verifier hook. Restrict its trust store to the SAN-validated leaf, never
    # the issuing CA. Explicit CA:FALSE prevents this anchor signing a child.
    # No client peer-DER callback exists: grpcio's trust-anchor matching may
    # treat an equivalent subject/public-key certificate as the same anchor.
    # This is not exact DER equality and cannot protect a compromised leaf key.
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
