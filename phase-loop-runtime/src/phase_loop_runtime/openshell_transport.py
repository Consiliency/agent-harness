"""Unregistered private-v1 protocol client; not an ExecutingBackend.

Inject the pinned generated protobuf module and an authenticated grpc.aio stub.
This module creates no channel, reads no settings and grants no capabilities.
Fresh handles require a previously fsynced lease; recovered handles are observe/
kill only. The in-memory attempt bits are not a durable journal or server fence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
from uuid import UUID

from google.protobuf.message import Message

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
class Observation:
    sandbox_ref: str
    admission_ready: bool
    create_settled: bool
    execution_claimed: bool
    fenced: bool
    destruction_observed: bool
    cleanup_pending: bool
    barrier_confirmed: bool


@dataclass(frozen=True)
class StreamResult:
    """Raw protocol exit, not a provider completion witness or accepted artifact."""

    exit_code: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


class ExecStream:
    """One local collector; wait never performs an RPC or extends its fixed end."""

    def __init__(self, session, stream, bound, end, output_cap_bytes, message_cap):
        self._session, self._stream, self._bound = session, stream, bound
        self._end = end
        self._cancelled = False
        self._is_owned = lambda: True
        self._task = asyncio.create_task(self._collect(output_cap_bytes, message_cap))
        self._task.add_done_callback(lambda t: None if t.cancelled() else t.exception())

    def cancel(self):
        """Discard locally; this is never a remote destruction acknowledgement."""
        self._cancelled = True
        self._stream.cancel()
        self._task.cancel()

    def _check(self):
        if (self._cancelled or self._session._kill_requested or not self._is_owned()
                or self._bound.cancelled.is_set()
                or asyncio.get_running_loop().time() >= self._end):
            self.cancel()
            raise TransportError("sandbox_placement_operation_timeout", uncertain=True)

    async def _collect(self, output_cap_bytes, message_cap):
        async def run():
            out, err = bytearray(), bytearray()
            exit_code, count = None, 0
            async for event in self._stream:
                self._check()
                count += 1
                if count > message_cap:
                    raise TransportError("message_limit", uncertain=True)
                kind = event.WhichOneof("payload")
                if exit_code is not None or kind not in ("stdout", "stderr", "exit"):
                    raise TransportError("invalid_exec_stream", uncertain=True)
                if kind == "exit":
                    exit_code = event.exit.exit_code
                else:
                    data = getattr(event, kind).data
                    if len(out) + len(err) + len(data) > output_cap_bytes:
                        raise TransportError("output_limit", uncertain=True)
                    (out if kind == "stdout" else err).extend(data)
            self._check()
            if exit_code is None:
                raise TransportError("missing_exec_exit", uncertain=True)
            return StreamResult(exit_code, bytes(out), bytes(err))

        try:
            self._check()
            remaining = self._end - asyncio.get_running_loop().time()
            return await self._session._bounded(run, OperationBound(remaining, self._bound.cancelled))
        finally:
            self._stream.cancel()

    async def wait(self, wait_s: float) -> StreamResult | None:
        """Return None on poll expiry, or the raw terminal exit plus EOF."""
        if type(wait_s) not in (int, float) or not math.isfinite(wait_s) or wait_s < 0:
            raise TransportError("invalid_bound")
        end = asyncio.get_running_loop().time() + wait_s
        try:
            while True:
                self._check()
                if self._task.done():
                    return self._task.result()
                left = end - asyncio.get_running_loop().time()
                if left <= 0:
                    return None
                await asyncio.wait((self._task,), timeout=min(left, 0.05))
        except asyncio.CancelledError:
            self.cancel()
            raise


class LeaseSession:
    """One authenticated workspace/owner/lease, confined to one asyncio loop.

    Default recovery mode forbids CREATE and EXEC even after a ready STATUS.
    `fresh=True` is only for a newly allocated, durably journaled lease ID.
    """

    def __init__(self, proto, stub, *, workspace: str, owner_id: str, lease_id: str,
                 fresh: bool = False, expected_generation: str | None = None):
        if not all(isinstance(v, str) and v and v.strip() == v
                   for v in (workspace, owner_id, lease_id)):
            raise TransportError("invalid_scope")
        self._proto = proto
        self._stub = stub
        self._workspace = workspace
        self._owner = owner_id
        self._lease = lease_id
        self._create_attempted = not fresh
        self._exec_attempted = not fresh
        self._kill_requested = False
        self._generation = None
        self._observation = None
        self._poisoned = False
        self._reservation = False
        self._exec_stream = None
        if expected_generation is not None:
            self._bind(expected_generation)

    @staticmethod
    def unsupported(*args, **kwargs):
        raise UnsupportedCapability()

    transfer = commit = collect = renew = unsupported

    def _request(self, bound, operation=None):
        if (type(bound.timeout_s) not in (int, float)
                or not 0 < bound.timeout_s < 315576000000 or not math.isfinite(bound.timeout_s)):
            raise TransportError("invalid_bound")
        if bound.cancelled.is_set():
            raise TransportError("sandbox_placement_operation_timeout")
        ns = int(bound.timeout_s * 1_000_000_000)
        if ns == 0:
            raise TransportError("invalid_bound")
        fields = dict(workspace_scope={"workspace": self._workspace}, owner_id=self._owner,
                      lease_id=self._lease,
                      bound={"seconds": ns // 1_000_000_000, "nanos": ns % 1_000_000_000})
        if operation is None:
            return self._proto.ExecCancellationLeaseRequest(**fields)
        return self._proto.ControlCancellationLeaseRequest(operation=operation, **fields)

    async def _bounded(self, run, bound):
        """Cancel the aio call on deadline/caller cancellation; never retry it."""
        end = asyncio.get_running_loop().time() + bound.timeout_s
        task = asyncio.ensure_future(run())
        try:
            while True:
                left = end - asyncio.get_running_loop().time()
                if left <= 0 or bound.cancelled.is_set():
                    raise TransportError("sandbox_placement_operation_timeout", uncertain=True)
                done, _ = await asyncio.wait((task,), timeout=min(left, 0.05))
                if done:
                    if bound.cancelled.is_set() or asyncio.get_running_loop().time() >= end:
                        raise TransportError("sandbox_placement_operation_timeout", uncertain=True)
                    return task.result()
        except (TransportError, asyncio.CancelledError):
            raise
        except Exception as exc:
            # grpc status only, never details(), repr(request), or exception prose.
            try:
                code = getattr(exc, "code", None)
                name = getattr(code(), "name", None) if callable(code) else None
                if type(name) is not str:
                    name = None
            except Exception:
                name = None
            mapped = {
                "DEADLINE_EXCEEDED": "sandbox_placement_operation_timeout",
                "PERMISSION_DENIED": "owner_workspace_refused",
                "UNAUTHENTICATED": "owner_workspace_refused",
                "FAILED_PRECONDITION": "transition_refused",
                "INVALID_ARGUMENT": "invalid_request",
                "ABORTED": "cas_conflict",
            }.get(name, "authority_unavailable")
            raise TransportError(mapped, uncertain=True) from None
        finally:
            if not task.done():
                task.cancel()
            # aio calls must cooperate with cancellation. Retrieve late exceptions
            # without extending the caller's bound or starting another RPC.
            task.add_done_callback(lambda t: None if t.cancelled() else t.exception())

    async def _control(self, request, bound):
        async def run():
            return await self._stub.ControlCancellationLease(request, timeout=bound.timeout_s)
        return await self._bounded(run, bound)

    async def enroll(self, bound: OperationBound):
        await self._control(self._request(bound, 1), bound)

    def _bind(self, reference):
        self._validate_reference(reference)
        if reference == f"reservation:{self._lease}":
            self._reservation = True
        else:
            self._generation = reference

    def _validate_reference(self, reference):
        if reference == f"reservation:{self._lease}" and self._generation is None:
            return
        try:
            parsed = UUID(reference)
        except (ValueError, TypeError, AttributeError):
            raise TransportError("invalid_generation", uncertain=True) from None
        if parsed.int == 0 or str(parsed) != reference:
            raise TransportError("invalid_generation", uncertain=True)
        if self._reservation or self._generation is not None and self._generation != reference:
            raise TransportError("generation_mismatch", uncertain=True)

    async def status(self, bound: OperationBound) -> Observation:
        response = None
        try:
            response = await self._control(self._request(bound, 5), bound)
            return self._observe(response)
        except TransportError:
            self._poisoned = True
            if response is not None and response.fenced:
                self._kill_requested = True
            raise

    def _observe(self, response):
        if not response.HasField("lease") or response.lease.lease_id != self._lease:
            raise TransportError("lease_mismatch", uncertain=True)
        self._validate_reference(response.lease.sandbox_ref)
        result = Observation(response.lease.sandbox_ref, **{
            key: getattr(response, key) for key in Observation.__dataclass_fields__
            if key != "sandbox_ref"
        })
        has_generation = result.sandbox_ref != f"reservation:{self._lease}"
        if (result.admission_ready and (not result.create_settled or result.fenced
                                       or result.execution_claimed or not has_generation)
                or result.barrier_confirmed and (not result.fenced or not result.create_settled
                                                or result.cleanup_pending
                                                or has_generation
                                                and not result.destruction_observed)
                or result.cleanup_pending == result.barrier_confirmed):
            raise TransportError("invalid_observation", uncertain=True)
        previous = self._observation
        if previous and any(getattr(previous, key) and not getattr(result, key)
                            for key in ("create_settled", "fenced", "execution_claimed", "destruction_observed",
                                        "barrier_confirmed")):
            raise TransportError("observation_regressed", uncertain=True)
        self._bind(result.sandbox_ref)
        self._observation = result
        if result.fenced:
            self._kill_requested = True
        return result

    async def create(self, create: Message, bound: OperationBound) -> str:
        if self._create_attempted or self._kill_requested:
            raise TransportError("create_not_repeatable")
        request = self._request(bound, 2)
        request.create.CopyFrom(create)
        spec = request.create.spec
        template = spec.template
        if (not spec.HasField("policy") or spec.command or spec.providers or spec.environment
                or template.environment or template.agent_socket or template.HasField("driver_config")
                or request.create.workload_template or request.create.service_exposures
                or spec.restart_policy != 1):
            raise TransportError("invalid_create")
        if spec.policy.network_policies:
            fs = spec.policy.filesystem
            paths = set(fs.read_only) | set(fs.read_write)
            if not set(PROXY_BASELINE_READ_ONLY + PROXY_BASELINE_READ_WRITE) <= paths:
                raise TransportError("missing_proxy_baseline")
        request.create.workspace_scope.workspace = self._workspace
        # Server selects the routable name and immutable UUID; neither is authority.
        request.create.name = ""
        request.create.await_main_process_attachment = True
        self._create_attempted = True
        response = await self._control(request, bound)
        if not response.HasField("sandbox"):
            raise TransportError("missing_generation", uncertain=True)
        if response.sandbox.metadata.workspace != self._workspace:
            raise TransportError("workspace_mismatch", uncertain=True)
        self._bind(response.sandbox.metadata.id)
        return self._generation

    async def dispatch(self, execute: Message, bound: OperationBound, *, stream_bound: OperationBound,
                       output_cap_bytes: int, message_cap: int) -> ExecStream:
        """Start exactly one RPC, without waiting for headers, output, or remote acceptance."""
        if (self._exec_attempted or self._kill_requested or self._poisoned or self._observation is None
                or not self._observation.admission_ready):
            raise TransportError("execute_not_permitted")
        if type(output_cap_bytes) is not int or output_cap_bytes < 0:
            raise TransportError("invalid_output_cap")
        if type(message_cap) is not int or message_cap <= 0:
            raise TransportError("invalid_message_cap")
        if stream_bound is None:
            raise UnsupportedCapability()
        self._request(stream_bound)  # finite lifetime required before any effect
        end = asyncio.get_running_loop().time() + stream_bound.timeout_s
        request = self._request(bound)
        request.exec.CopyFrom(execute)
        if request.exec.tty:
            raise TransportError("invalid_exec")
        request.exec.workspace_scope.workspace = self._workspace
        request.exec.sandbox = self._generation
        self._exec_attempted = True
        stream = None

        async def start():
            nonlocal stream
            # grpc.aio's call constructor is nonblocking. Its deadline covers the
            # whole stream; the private request field bounds server dispatch only.
            stream = self._stub.ExecCancellationLease(request, timeout=stream_bound.timeout_s)

        try:
            await self._bounded(start, bound)
            self._exec_stream = ExecStream(self, stream, stream_bound, end, output_cap_bytes, message_cap)
            self._exec_stream._check()
            return self._exec_stream
        except BaseException:
            if self._exec_stream is not None:
                self._exec_stream.cancel()
            elif stream is not None:
                stream.cancel()
            raise

    async def execute(self, execute: Message, bound: OperationBound, *, output_cap_bytes: int) -> StreamResult:
        """Compatibility wrapper: one bound for dispatch and full collection.

        New integrations use dispatch with an explicit message cap. The legacy
        cap permits one one-byte event per output byte plus the terminal event.
        """
        message_cap = output_cap_bytes + 1 if type(output_cap_bytes) is int else 1
        handle = await self.dispatch(execute, bound, stream_bound=bound,
                                     output_cap_bytes=output_cap_bytes, message_cap=message_cap)
        result = await handle.wait(bound.timeout_s)
        if result is None:
            handle.cancel()
            raise TransportError("sandbox_placement_operation_timeout", uncertain=True)
        return result

    async def kill(self, bound: OperationBound) -> None:
        self._kill_requested = True
        if self._exec_stream is not None:
            self._exec_stream.cancel()
        # A deadline can occur BEFORE durable K2. Only STATUS proves a fence.
        started = asyncio.get_running_loop().time()
        response = await self._control(self._request(bound, 3), bound)
        if not response.barrier_confirmed:
            raise TransportError("sandbox_placement_operation_timeout", uncertain=True)
        left = bound.timeout_s - (asyncio.get_running_loop().time() - started)
        if left <= 0:
            raise TransportError("sandbox_placement_operation_timeout", uncertain=True)
        observed = await self.status(OperationBound(left, bound.cancelled))
        if not observed.barrier_confirmed:
            raise TransportError("sandbox_placement_operation_timeout", uncertain=True)

    async def list_owned(self, bound: OperationBound) -> tuple[tuple[str, str], ...]:
        response = await self._control(self._request(bound, 4), bound)
        pairs = []
        leases, refs = set(), set()
        for entry in response.entries:
            ref, lease = entry.sandbox_ref, entry.lease_id
            if (not lease or lease in leases or ref in refs
                    or ref == self._generation and lease != self._lease):
                raise TransportError("invalid_inventory", uncertain=True)
            if ref != f"reservation:{lease}":
                try:
                    valid = str(UUID(ref)) == ref and UUID(ref).int != 0
                except ValueError:
                    valid = False
                if not valid:
                    raise TransportError("invalid_inventory", uncertain=True)
            pairs.append((ref, lease))
            leases.add(lease)
            refs.add(ref)
        for ref, lease in pairs:
            if lease == self._lease:
                try:
                    self._bind(ref)
                except TransportError:
                    self._poisoned = True
                    raise
        return tuple(pairs)
