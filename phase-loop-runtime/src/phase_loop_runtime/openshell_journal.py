"""Unregistered journal/transport adapter. No channel factory or executing backend."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError

from .openshell_transport import LeaseSession, TransportError
from .placement_lease import Lease, _valid_entry
from .sandbox_placement import PlacementUnavailable, _TIMEOUT


class JournalSession:
    """Attach once to an exclusively held lease; disk recovery never grants dispatch."""

    def __init__(self, lease: Lease, proto, stub, *, workspace: str):
        self.lease = lease
        fresh, reference = lease.attach_transport(self)
        self._session = LeaseSession(proto, stub, workspace=workspace,
                                     owner_id=lease.owner_id, lease_id=lease.lease_id,
                                     fresh=fresh, expected_generation=reference)

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

    async def execute(self, request, bound, *, output_cap_bytes):
        self.lease.mark_dispatch(self, "execute")
        try:
            return await self._session.execute(request, bound, output_cap_bytes=output_cap_bytes)
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


class ReaperAdapter:
    """Synchronous existing-reaper bridge to an injected, running aio loop.

    Call reap from outside that loop. The reaper owns the file locks and writes;
    even a late RPC completion cannot mutate a journal after its lock is released.
    """

    def __init__(self, proto, stub, *, loop, workspace: str, owner_id: str):
        self._proto, self._stub, self._loop = proto, stub, loop
        self._workspace, self._owner = workspace, owner_id

    def _session(self, lease_id, reference=None):
        return LeaseSession(self._proto, self._stub, workspace=self._workspace,
                            owner_id=self._owner, lease_id=lease_id,
                            expected_generation=reference)

    def _run(self, coroutine, bound):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
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
