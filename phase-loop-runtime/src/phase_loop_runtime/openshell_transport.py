"""Unregistered coordinator and stock exec clients.

Inject stock-compatible protobuf bindings and an authenticated grpc.aio stub.
This module creates no channel, reads no settings and grants no capabilities.
Fresh handles require a previously fsynced lease; recovered handles are observe/
kill only. The in-memory attempt bits are not a durable journal or server fence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
from uuid import UUID


from .sandbox_placement import OperationBound


PROXY_BASELINE_READ_ONLY = ("/usr", "/lib", "/etc", "/app", "/var/log", "/proc", "/dev/urandom")
PROXY_BASELINE_READ_WRITE = ("/tmp", "/dev/null")


class TransportError(RuntimeError):
    """Input-free error; uncertainty never authorizes another dispatch."""

    def __init__(self, code: str, *, uncertain: bool = False):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


class UnsupportedCapability(TransportError):
    def __init__(self):
        super().__init__("unsupported_capability")


@dataclass(frozen=True)
class StreamResult:
    """Raw protocol exit, not a provider completion witness or accepted artifact."""

    exit_code: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


import hashlib
from importlib.resources import files
import json
import os
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid5, NAMESPACE_URL

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

_SCHEMA = json.loads((files('phase_loop_runtime') /
    'contracts/placement/coordinator-v1.schema.json').read_text())


def validate_wire(kind, value):
    """Shared schema plus asserted formats; response extensions remain allowed."""
    validator = Draft202012Validator({'$ref': '#/$defs/' + kind, '$defs': _SCHEMA['$defs']},
                                    format_checker=FormatChecker())
    if not validator.is_valid(value):
        raise TransportError('invalid_coordinator_message', uncertain=True)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value or not UUID(value).int:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise TransportError('invalid_lease_identity', uncertain=True) from None
    return value


class CallerAllowance:
    """One fixed caller end, reused across requests, polling and pagination.

    Construct once at the operation boundary. Responses never reset this end.
    """

    def __init__(self, bound: OperationBound):
        if (type(bound.timeout_s) not in (int, float) or
                not math.isfinite(bound.timeout_s) or not 0 < bound.timeout_s < 315576000000):
            raise TransportError('invalid_bound')
        self.end = time.monotonic() + bound.timeout_s
        self.cancelled = bound.cancelled

    def remaining(self):
        left = self.end - time.monotonic()
        if self.cancelled.is_set() or left < .001:
            raise TransportError('sandbox_placement_operation_timeout', uncertain=True)
        return left

    async def run(self, operation, *, cap_s=None):
        duration = self.remaining()
        if cap_s is not None:
            duration = min(duration, cap_s)
        end = time.monotonic() + duration
        task = asyncio.ensure_future(operation())
        try:
            while True:
                left = min(self.remaining(), end - time.monotonic())
                if left <= 0:
                    raise TransportError('sandbox_placement_operation_timeout', uncertain=True)
                done, _ = await asyncio.wait((task,), timeout=min(left, .02))
                if done:
                    self.remaining()
                    if time.monotonic() >= end:
                        raise TransportError('sandbox_placement_operation_timeout', uncertain=True)
                    return task.result()
        except (TransportError, asyncio.CancelledError):
            raise
        except Exception:
            raise TransportError('sandbox_placement_operation_timeout', uncertain=True) from None
        finally:
            if not task.done():
                task.cancel()
            task.add_done_callback(lambda t: None if t.cancelled() else t.exception())


class CoordinatorError(TransportError):
    def __init__(self, code, reason, *, uncertain=True):
        super().__init__(code, uncertain=uncertain)
        self.reason = reason


class CoordinatorClient:
    """Unregistered HTTPS JSON client; no implicit recovery or mutation retries.

    Cleanup obligations are conservative client evidence. Even a terminal status
    or kill reply does not clear them: SL-2 must prove the barrier AND inventory.
    The local journal owner is explicitly bound and never rewritten as a cert CN.
    """

    def __init__(self, config, *, local_owner_id, clock=time.monotonic):
        _, self._tls = config.validate(local_owner_id)
        self.config = config
        self.local_owner_id = local_owner_id
        self._url = urlsplit(config.endpoint)
        self._clock = clock
        self.cleanup_obligations = set()
        self.poisoned_leases = set()
        self._observations = {}
        self._reserve_attempted, self._create_attempted = set(), set()
        self._bindings = {}

    async def _http(self, method, path, body, allowance):
        writer = None
        sent = False
        async def exchange():
            nonlocal writer, sent
            try:
                async with asyncio.timeout(min(allowance.remaining(), self.config.connect_timeout_s)):
                    reader, writer = await asyncio.open_connection(self._url.hostname, self._url.port or 443,
                        ssl=self._tls, server_hostname=self._url.hostname,
                        ssl_handshake_timeout=min(allowance.remaining(), self.config.connect_timeout_s),
                        limit=min(self.config.receive_limit_bytes, 65536))
            except (OSError, TimeoutError):
                raise TransportError('sandbox_placement_unreachable', uncertain=False) from None
            wire = b'' if body is None else json.dumps(body, allow_nan=False, separators=(',', ':')).encode()
            ms = min(30000, int(allowance.remaining() * 1000))
            host = self._url.netloc
            head = (f'{method} /v1{path} HTTP/1.1\r\nHost: {host}\r\n'
                    f'X-Deadline-Ms: {ms}\r\nAccept: application/json\r\n'
                    f'Content-Type: application/json\r\nContent-Length: {len(wire)}\r\nConnection: close\r\n\r\n')
            # Once write is attempted, a partial send cannot be ruled out.
            sent = True
            writer.write(head.encode('ascii') + wire)
            await writer.drain()
            raw = await reader.readuntil(b'\r\n\r\n')
            if len(raw) > 65536:
                raise TransportError('invalid_http_response', uncertain=True)
            lines = raw.decode('ascii').split('\r\n')
            version, status, _ = lines[0].split(' ', 2)
            if version != 'HTTP/1.1' or not status.isdigit():
                raise TransportError('invalid_http_response', uncertain=True)
            headers = {}
            for line in lines[1:-2]:
                key, value = line.split(':', 1)
                key = key.lower()
                if key in headers:
                    raise TransportError('invalid_http_response', uncertain=True)
                headers[key] = value.strip()
            if headers.get('content-type', '').split(';')[0].lower() != 'application/json':
                raise TransportError('invalid_http_response', uncertain=True)
            cap = self.config.receive_limit_bytes
            if 'transfer-encoding' in headers:
                if headers['transfer-encoding'].lower() != 'chunked' or 'content-length' in headers:
                    raise TransportError('invalid_http_response', uncertain=True)
                data = bytearray()
                while True:
                    size = int((await reader.readuntil(b'\r\n')).strip(), 16)
                    if size < 0 or len(data) + size > cap:
                        raise TransportError('response_limit', uncertain=True)
                    if size == 0:
                        if await reader.readexactly(2) != b'\r\n':
                            raise TransportError('invalid_http_response', uncertain=True)
                        break
                    data.extend(await reader.readexactly(size))
                    if await reader.readexactly(2) != b'\r\n':
                        raise TransportError('invalid_http_response', uncertain=True)
            else:
                size = int(headers['content-length'])
                if not 0 <= size <= cap:
                    raise TransportError('response_limit', uncertain=True)
                data = await reader.readexactly(size)
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError
                    result[key] = value
                return result
            value = json.loads(bytes(data).decode('utf-8'), object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            return int(status), value
        try:
            return await allowance.run(exchange, cap_s=30)
        except TransportError as error:
            if not sent and error.code == 'sandbox_placement_operation_timeout':
                raise TransportError('sandbox_placement_unreachable', uncertain=False) from None
            raise
        finally:
            if writer is not None:
                # Abort rather than waiting for a TLS peer's shutdown response.
                writer.transport.abort()

    async def _request(self, method, path, body, allowance, kind, lease=None, operation=None):
        if lease is not None:
            _uuid(lease)
        try:
            # Snapshot caller-owned JSON before the first await. A caller cannot
            # change a validated policy while TLS connection setup yields.
            if body is not None:
                body = json.loads(json.dumps(body, allow_nan=False))
            status, value = await self._http(method, path, body, allowance)
            is_error = not 200 <= status < 300
            if not is_error:
                try:
                    validate_wire(kind, value)
                except TransportError:
                    is_error = True
            if is_error:
                # Status is advisory: a typed error is an error even under 2xx.
                validate_wire('ErrorBody', value)
                if value['lease_id'] not in (None, lease):
                    raise TransportError('lease_mismatch', uncertain=True)
                code = value['code']
                if code == 'unavailable' and operation != 'reserve':
                    raise TransportError('sandbox_placement_operation_timeout', uncertain=True)
                safe = operation == 'reserve' and code in ('unavailable', 'at_capacity', 'not_enrolled',
                    'owner_mismatch', 'invalid_request', 'workload_unsupported')
                raise CoordinatorError(code, value['reason'], uncertain=not safe)
            validate_wire(kind, value)
            if kind == 'LeaseStatus':
                value = self._observe(value, lease)
            allowance.remaining()
            return value
        except (TransportError, asyncio.CancelledError) as error:
            if lease:
                if operation == 'reserve' and isinstance(error, TransportError) and not error.uncertain:
                    self.cleanup_obligations.discard(lease)
                    self._reserve_attempted.discard(lease)
                    self._bindings.pop(lease, None)
                else:
                    self.poisoned_leases.add(lease)
                    self.cleanup_obligations.add(lease)
                    if isinstance(error, TransportError):
                        error.uncertain = True
                        if error.code == 'sandbox_placement_unreachable':
                            raise TransportError('sandbox_placement_operation_timeout', uncertain=True) from None
            # Only admission and advisory capacity may interpret a pre-send
            # failure as unreachable. Confirmation without a lease (inventory)
            # is still incomplete evidence and cannot authorize release.
            if (isinstance(error, TransportError)
                    and error.code == 'sandbox_placement_unreachable'
                    and operation not in ('reserve', 'capacity')):
                raise TransportError('sandbox_placement_operation_timeout', uncertain=True) from None
            raise

    def _observe(self, value, lease=None, *, commit=True):
        validate_wire('LeaseStatus', value)
        identity, sandbox, flags, state = value['lease_id'], value['sandbox_id'], value['flags'], value['state']
        _uuid(identity)
        if lease is not None and identity != lease:
            raise TransportError('lease_mismatch', uncertain=True)
        if sandbox is not None:
            _uuid(sandbox)
        previous = self._observations.get(identity)
        if previous:
            if previous['sandbox_id'] is not None and sandbox != previous['sandbox_id']:
                raise TransportError('generation_mismatch', uncertain=True)
            # All historical flags are monotonic, including cleanup evidence.
            if any(previous['flags'][key] and not flags[key] for key in previous['flags']
                   if key in _SCHEMA['$defs']['LeaseFlags']['properties']):
                raise TransportError('observation_regressed', uncertain=True)
        binding = value['binding']
        invalid = (
            state not in ('tombstone', 'killing') and not flags['reserved']
            or state == 'tombstone' and (flags['reserved'] or not flags['fenced'] or not flags['barrier_confirmed'])
            or state in ('reserved', 'creating') and (flags['fenced'] or flags['ready'])
            or state == 'ready' and (not flags['ready'] or not flags['create_settled'] or sandbox is None or flags['fenced'])
            or state == 'killing' and (not flags['fenced'] or flags['barrier_confirmed'])
            or state == 'destroyed' and (not flags['fenced'] or not flags['barrier_confirmed'])
            or flags['ready'] and (not flags['create_settled'] or sandbox is None)
            or state == 'expired' and not flags['expired']
            or flags['barrier_confirmed'] and (not flags['fenced'] or not flags['create_settled']
                or sandbox is not None and not flags['destruction_observed'] or binding['label_matches'] or binding['duplicates'])
        )
        if invalid:
            raise TransportError('invalid_observation', uncertain=True)
        if commit:
            # Keep a private copy: returned dictionaries cannot erase history.
            self._observations[identity] = json.loads(json.dumps(value))
            if flags['reserved'] or state == 'killing':
                self.cleanup_obligations.add(identity)
        return value

    def validate_create(self, body, binding):
        """Validate full create inputs before reserving; no remote effects."""
        try:
            validate_wire('CreateBody', body)
        except TransportError:
            raise TransportError('invalid_create') from None
        if body['service_exposures']:
            raise TransportError('invalid_create')
        try:
            digest = 'sha256:' + hashlib.sha256(rfc8785.dumps(body['policy'])).hexdigest()
        except (ValueError, TypeError):
            raise TransportError('invalid_create') from None
        if (binding is None or body['policy_digest'] != digest or digest != binding['policy_digest']
                or body['image'].rsplit('@', 1)[1] != binding['image_digest']):
            raise TransportError('digest_mismatch')

    async def reserve(self, lease, body, allowance, *, create_body=None):
        """Reserve once; supply create_body to refuse invalid creates before admission.

        Split lifecycle callers can preflight with validate_create instead. Create
        always validates again because a reservation must retain cleanup on refusal.
        """
        try:
            _uuid(lease)
            validate_wire('ReserveBody', body)
        except TransportError as error:
            # Local validation precedes the attempt marker and remote effects.
            # Shared validators remain conservative for response parsing.
            error.uncertain = type(lease) is str and lease in self.cleanup_obligations
            raise
        if body['workload'] == 'pi-runner':
            raise TransportError('invalid_workload', uncertain=lease in self.cleanup_obligations)
        if create_body is not None:
            try:
                self.validate_create(create_body, body)
            except TransportError as error:
                error.uncertain = lease in self.cleanup_obligations
                raise
        if lease in self._reserve_attempted or lease in self.cleanup_obligations:
            raise TransportError('reserve_not_repeatable', uncertain=lease in self.cleanup_obligations)
        self._reserve_attempted.add(lease)
        self.cleanup_obligations.add(lease)
        self._bindings[lease] = dict(body)
        return await self._request('POST', '/leases/' + lease, body, allowance, 'LeaseStatus', lease, 'reserve')

    async def create(self, lease, body, allowance):
        _uuid(lease)
        try:
            self.validate_create(body, self._bindings.get(lease))
            previous = self._observations.get(lease)
            if (lease in self._create_attempted or lease in self.poisoned_leases
                    or previous and (previous['flags']['fenced'] or previous['flags']['expired'])):
                raise TransportError('create_not_repeatable')
        except TransportError as error:
            error.uncertain = lease in self.cleanup_obligations
            raise
        self._create_attempted.add(lease)
        return await self._request('POST', '/leases/' + lease + '/sandbox', body, allowance, 'LeaseStatus', lease, 'create')

    async def status(self, lease, allowance):
        return await self._request('GET', '/leases/' + _uuid(lease), None, allowance, 'LeaseStatus', lease, 'status')

    async def renew(self, lease, extend_s, allowance):
        body = {'extend_s': extend_s}
        try:
            validate_wire('RenewBody', body)
        except TransportError as error:
            error.uncertain = lease in self.cleanup_obligations
            raise
        return await self._request('POST', '/leases/' + _uuid(lease) + '/renew', body, allowance, 'LeaseStatus', lease, 'renew')

    async def kill(self, lease, allowance):
        self.cleanup_obligations.add(_uuid(lease))
        return await self._request('POST', '/leases/' + lease + '/kill', {}, allowance, 'LeaseStatus', lease, 'kill')

    async def capacity(self, allowance):
        return await self._request('GET', '/capacity', None, allowance, 'CapacityReading', operation='capacity')

    async def poll_ready(self, lease, allowance, *, interval_s=.05):
        if type(interval_s) not in (int, float) or not math.isfinite(interval_s) or interval_s <= 0:
            raise TransportError('invalid_bound', uncertain=lease in self.cleanup_obligations)
        while True:
            value = await self.status(lease, allowance)
            if value['flags']['fenced'] or value['flags']['expired']:
                raise TransportError('lease_not_ready', uncertain=True)
            if value['flags']['ready']:
                return value
            await allowance.run(lambda: asyncio.sleep(interval_s))

    async def list_owned(self, allowance):
        """Complete validated evidence, including terminal entries, never partial."""
        while True:
            allowance.remaining()
            started = self._clock()
            snapshot, token, seen_tokens, entries = None, None, set(), {}
            try:
                while True:
                    query = {'page_size': 200}
                    if token is not None:
                        query['page_token'] = token
                    page = await self._request('GET', '/leases?' + urlencode(query), None, allowance, 'InventoryPage')
                    if (self._clock() - started >= 60 or not page['snapshot'] or
                            snapshot is not None and page['snapshot'] != snapshot):
                        raise CoordinatorError('snapshot_expired', None)
                    snapshot = page['snapshot']
                    for entry in page['items']:
                        identity = entry['lease_id']
                        if identity in entries:
                            raise TransportError('invalid_inventory', uncertain=True)
                        self._observe(entry, commit=False)
                        if entry['sandbox_id'] is not None and any(
                                prior['sandbox_id'] == entry['sandbox_id'] for prior in entries.values()):
                            raise TransportError('invalid_inventory', uncertain=True)
                        entries[identity] = entry
                    token = page['next_page_token']
                    if token is None:
                        allowance.remaining()
                        if self._clock() - started >= 60:
                            raise CoordinatorError('snapshot_expired', None)
                        # Validate all pages before publishing any new history.
                        for entry in entries.values():
                            self._observe(entry)
                        return tuple(entries.values())
                    if not token or token in seen_tokens:
                        raise CoordinatorError('snapshot_expired', None)
                    seen_tokens.add(token)
            except CoordinatorError as error:
                if error.code != 'snapshot_expired':
                    raise
                # Yield without refreshing the original allowance.
                await allowance.run(lambda: asyncio.sleep(0))


def exec_request_id(lease, attempt):
    _uuid(lease)
    if type(attempt) is not int or attempt < 1:
        raise TransportError('invalid_exec_attempt')
    return str(uuid5(NAMESPACE_URL, f'agent-harness/openshell/exec/{lease}/{attempt}'))


class StockExecChannel:
    """Stock single-dispatch channel, no control-plane or source RPC surface."""

    def __init__(self, channel, proto, local_owner_id):
        self._proto, self._local_owner = proto, local_owner_id
        self._call = channel.unary_stream('/openshell.v1.OpenShell/ExecSandbox',
            request_serializer=proto.ExecSandboxRequest.SerializeToString,
            response_deserializer=proto.ExecSandboxEvent.FromString)
        self._attempted, self._bindings, self._active = set(), {}, {}
        self._invalidated = set()
        self._closed = False
        self._loop, self._pid = asyncio.get_running_loop(), os.getpid()

    def _check(self):
        try:
            valid_loop = self._loop is asyncio.get_running_loop()
        except RuntimeError:
            valid_loop = False
        if self._closed or self._pid != os.getpid() or not valid_loop:
            raise TransportError('invalid_channel_context')

    def bind_lease(self, lease, sandbox_id, *, local_owner_id):
        self._check()
        _uuid(lease)
        _uuid(sandbox_id)
        if local_owner_id != self._local_owner:
            raise TransportError('invalid_local_owner_binding')
        if lease in self._bindings and self._bindings[lease] != sandbox_id:
            raise TransportError('generation_mismatch', uncertain=True)
        self._bindings[lease] = sandbox_id
        return StockExecSession(self, lease, sandbox_id)

    def invalidate_lease(self, lease):
        self._check()
        self._invalidated.add(_uuid(lease))
        for call, identity in tuple(self._active.items()):
            if identity == lease:
                call.cancel()

    def close(self):
        self._closed = True
        for call in tuple(self._active):
            call.cancel()


class StockExecSession:
    """Caller must durably record the attempt before invoking execute.

    The registry prevents repeats across handles on this channel; SL-2's journal
    prevents repeats across process/channel lifetimes. Neither is a remote fence.
    A kill race invalidates all results; only destruction provides a server fence.
    """

    def __init__(self, channel, lease, sandbox):
        self._channel, self._lease, self._sandbox = channel, lease, sandbox
        self._invalidated = False
        self._stream = None

    def invalidate(self):
        self._invalidated = True
        self._channel.invalidate_lease(self._lease)
        if self._stream is not None:
            self._stream.cancel()

    async def execute(self, execute, allowance, *, attempt, output_cap_bytes, message_cap):
        channel = self._channel
        channel._check()
        if self._lease in channel._attempted or self._invalidated or self._lease in channel._invalidated:
            raise TransportError('exec_not_repeatable', uncertain=True)
        if type(output_cap_bytes) is not int or output_cap_bytes < 0:
            raise TransportError('invalid_output_cap')
        if type(message_cap) is not int or message_cap <= 0:
            raise TransportError('invalid_message_cap')
        request = channel._proto.ExecSandboxRequest()
        request.CopyFrom(execute)
        # Stock requires an explicit named workspace selector for routing. It
        # grants no coordinator/journal authority; mTLS remains the identity.
        if (request.tty or request.workspace_scope.WhichOneof('selection') != 'workspace'
                or not request.workspace_scope.workspace):
            raise TransportError('invalid_exec')
        request.sandbox = self._sandbox
        request.request_id = exec_request_id(self._lease, attempt)
        left = allowance.remaining()
        request.execution_timeout.FromNanoseconds(max(1, int(left * 1_000_000_000)))
        if request.ByteSize() > 4 * 1024 * 1024:
            raise TransportError('exec_input_limit')
        channel._attempted.add(self._lease)  # Before the only call constructor.
        try:
            stream = channel._call(request, timeout=allowance.remaining(), wait_for_ready=False)
        except TransportError:
            raise
        except Exception:
            raise TransportError('sandbox_placement_operation_timeout', uncertain=True) from None
        self._stream = stream
        channel._active[stream] = self._lease
        async def collect():
            out, err, count, exit_code = bytearray(), bytearray(), 0, None
            async for event in stream:
                allowance.remaining()
                channel._check()
                if self._invalidated or self._lease in channel._invalidated:
                    raise TransportError('exec_invalidated', uncertain=True)
                count += 1
                if count > message_cap:
                    raise TransportError('message_limit', uncertain=True)
                kind = event.WhichOneof('payload')
                if exit_code is not None or kind not in ('stdout', 'stderr', 'exit'):
                    raise TransportError('invalid_exec_stream', uncertain=True)
                if kind == 'exit':
                    exit_code = event.exit.exit_code
                else:
                    data = getattr(event, kind).data
                    if len(out) + len(err) + len(data) > output_cap_bytes:
                        raise TransportError('output_limit', uncertain=True)
                    (out if kind == 'stdout' else err).extend(data)
            channel._check()
            if exit_code is None or self._invalidated or self._lease in channel._invalidated:
                raise TransportError('invalid_exec_stream', uncertain=True)
            return StreamResult(exit_code, bytes(out), bytes(err))
        try:
            return await allowance.run(collect)
        finally:
            stream.cancel()
            channel._active.pop(stream, None)
