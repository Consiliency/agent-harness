"""Unregistered journal/transport adapter. No channel factory or executing backend."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import TimeoutError

from .openshell_transport import LeaseSession, TransportError
from .placement_lease import JournalReapingBackend, Lease, _valid_entry, recover_lease
from .sandbox_placement import PlacementUnavailable, _TIMEOUT


class JournalSession:
    """Attach once to an exclusively held lease; disk recovery never grants dispatch."""

    def __init__(self, lease: Lease, proto, stub, *, workspace: str):
        self.lease = lease
        fresh, reference = lease.attach_transport(self)
        try:
            self._session = LeaseSession(proto, stub, workspace=workspace,
                                         owner_id=lease.owner_id, lease_id=lease.lease_id,
                                         fresh=fresh, expected_generation=reference)
        except BaseException:
            lease.fence()
            raise

    async def create(self, request, bound):
        self.lease.mark_dispatch(self, "create")
        try:
            reference = await self._session.create(request, bound)
            self.lease.record_transport_ref(self, reference)
            return reference
        except BaseException:
            self.lease.fence()
            raise

    async def status(self, bound):
        observed = await self._session.status(bound)
        self.lease.record_transport_ref(self, observed.sandbox_ref)
        return observed

    async def dispatch(self, request, bound, *, stream_bound, output_cap_bytes, message_cap):
        # Refuse indefinite execution before writing the durable attempt marker.
        if stream_bound is None:
            self._session.unsupported()
        self.lease.mark_dispatch(self, "execute")
        handle = None
        try:
            handle = await self._session.dispatch(request, bound, stream_bound=stream_bound,
                                                  output_cap_bytes=output_cap_bytes, message_cap=message_cap)
            handle._is_owned = lambda: self.lease.held and not self.lease.fenced
            self.lease.validate_live_binding(self)
            return handle
        except BaseException:
            if handle is not None:
                handle.cancel()
            self.lease.fence()
            raise

    async def execute(self, request, bound, *, output_cap_bytes):
        message_cap = output_cap_bytes + 1 if type(output_cap_bytes) is int else 1
        handle = await self.dispatch(request, bound, stream_bound=bound,
                                     output_cap_bytes=output_cap_bytes, message_cap=message_cap)
        try:
            return await handle.wait(bound.timeout_s)
        except BaseException:
            self.lease.fence()
            raise

    async def kill(self, bound):
        self.lease.fence()
        try:
            await self._session.kill(bound)
            # KILL's validated STATUS is the authority for the recovered reference.
            self.lease.record_transport_ref(self, self._session._observation.sandbox_ref)
            self.lease.note_killed()
        except BaseException:
            self.lease.abandon()
            raise

    async def list_owned(self, bound):
        return await self._session.list_owned(bound)


class ReaperAdapter(JournalReapingBackend):
    """Synchronous existing-reaper bridge to an injected, running aio loop.

    Call reap from outside that loop. The reaper owns the file locks and writes;
    even a late RPC completion cannot mutate a journal after its lock is released.
    """

    def __init__(self, proto, stub, *, loop, workspace: str, owner_id: str):
        self._proto, self._stub, self._loop = proto, stub, loop
        self._workspace, self._owner = workspace, owner_id
        self._pid = os.getpid()

    def validate_reaper_context(self):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if (running is not None or self._pid != os.getpid()
                or self._loop.is_closed() or not self._loop.is_running()):
            raise ValueError("journal bridge requires an external thread and a running loop")

    def _session(self, lease_id, reference=None):
        return LeaseSession(self._proto, self._stub, workspace=self._workspace,
                            owner_id=self._owner, lease_id=lease_id,
                            expected_generation=reference)

    def _run(self, coroutine, bound):
        try:
            self.validate_reaper_context()
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except BaseException:
            coroutine.close()
            raise
        try:
            return future.result(timeout=bound.timeout_s)
        except TimeoutError:
            future.cancel()
            raise PlacementUnavailable(_TIMEOUT) from None
        except TransportError as exc:
            raise PlacementUnavailable(exc.code) from None

    def kill_journaled(self, owner_id, lease_id, entry, bound):
        if owner_id != self._owner or not _valid_entry(entry, lease_id):
            raise ValueError("invalid lease journal")
        session = self._session(lease_id, entry["sandbox_ref"])

        async def kill():
            await session.kill(bound)
            return session._observation.sandbox_ref

        return self._run(kill(), bound)

    def list_owned(self, owner_id, bound):
        if owner_id != self._owner:
            raise ValueError("journal owner mismatch")
        return self._run(self._session("inventory").list_owned(bound), bound)


class OpenShellBackend(ReaperAdapter):
    """Unregistered cleanup-only connection; deliberately not an ExecutingBackend.

    Direct kill recovers an existing journal exclusively and retains it for reap's
    complete LIST check. RPC tasks never receive the journal handle.
    """

    def kill(self, lease_id, bound):
        self.validate_reaper_context()
        lease = recover_lease(lease_id)
        try:
            lease.attach_transport(self)
            reference = self.kill_journaled(lease.owner_id, lease_id, dict(lease._entry), bound)
            lease.record_transport_ref(self, reference)
            lease.note_killed()
        finally:
            lease.abandon()
