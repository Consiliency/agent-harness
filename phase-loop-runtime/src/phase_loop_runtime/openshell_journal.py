"""Unregistered coordinator journal adapter. Recovery authorizes cleanup only."""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError
import json
import os
from uuid import UUID, uuid4

from .openshell_transport import CallerAllowance, CoordinatorError, TransportError, validate_wire
from .placement_lease import (
    JournalReapingBackend, Lease, _lease_dir, _valid_entry, recover_lease,
)
from .sandbox_placement import PlacementUnavailable, _TIMEOUT


class ForkJournalRefusal(TransportError):
    def __init__(self):
        super().__init__('sandbox_placement_fork_journal_refused', uncertain=True)


def refuse_fork_entries():
    """No migration or erasure: an operator must resolve any fork-era entry."""
    directory = _lease_dir()
    if not directory.exists():
        return
    for path in directory.glob('*.json'):
        try:
            # Do not follow a substituted journal symlink.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                value = json.loads(os.read(fd, 65536).split(b'\n', 1)[0])
            finally:
                os.close(fd)
        except (OSError, ValueError):
            raise ForkJournalRefusal() from None
        if not isinstance(value, dict):
            raise ForkJournalRefusal()
        if (str(value.get('backend', '')).startswith('openshell')
                or str(value.get('root', '')).startswith('openshell:')):
            if not _valid_entry(value, path.stem) or not value.get('coordinator_lease_id'):
                raise ForkJournalRefusal()


def outstanding(values):
    """Terminal entries remain evidence, but never outstanding inventory pairs."""
    return tuple((value['lease_id'], UUID(value['lease_id']).hex) for value in values
                 if value['state'] not in ('tombstone', 'destroyed', 'expired')
                 or not value['flags']['barrier_confirmed'])


class JournalSession:
    """One exclusively held journal, durable attempts and immutable sandbox binding."""
    def __init__(self, lease: Lease, client, exec_channel=None):
        if lease.owner_id != client.local_owner_id:
            raise TransportError('journal_owner_mismatch', uncertain=True)
        self.lease, self.client, self.exec_channel = lease, client, exec_channel
        self.fresh, _ = lease.attach_transport(self)
        if not lease._entry.get('coordinator_lease_id'):
            if not self.fresh:
                raise ForkJournalRefusal()
            lease.record_coordinator(self, coordinator_lease_id=str(UUID(lease.lease_id)))
        self.client_uuid = lease._entry['coordinator_lease_id']
        self.reference = self.client_uuid  # Stable even for never-reserved kills.
        self.sandbox_id = lease._entry.get('coordinator_sandbox_id')
        self.observation = None
        self.inventory = ()
        self._exec = None

    def _live(self):
        self.lease.validate_live_binding(self)
        if not self.fresh:
            raise TransportError('recovered_dispatch_forbidden', uncertain=True)

    def _observe(self, value):
        validate_wire('LeaseStatus', value)
        if value['lease_id'] != self.client_uuid:
            self.lease.fence()
            raise TransportError('lease_mismatch', uncertain=True)
        sandbox = value['sandbox_id']
        if self.sandbox_id is not None and sandbox != self.sandbox_id:
            self.lease.fence()
            raise TransportError('generation_mismatch', uncertain=True)
        if sandbox is not None and self.sandbox_id is None:
            self.lease.record_coordinator(self, coordinator_sandbox_id=sandbox)
            self.sandbox_id = sandbox
        # Keep only contract fields, never remote extension prose or result bytes.
        evidence = {key: value[key] for key in ('lease_id', 'sandbox_id', 'state', 'expires_at')}
        evidence['flags'] = {key: value['flags'][key] for key in (
            'reserved', 'create_settled', 'ready', 'exec_claimed', 'fenced',
            'destruction_observed', 'cleanup_pending', 'barrier_confirmed', 'expired')}
        evidence['binding'] = {key: value['binding'][key] for key in ('label_matches', 'duplicates')}
        evidence['reclaims'] = [{key: record[key] for key in (
            'sandbox_id', 'reason', 'outcome', 'at')} for record in value.get('reclaims', ())]
        self.lease.record_coordinator(self, coordinator_evidence=evidence)
        self.observation = evidence
        self.lease.record_transport_ref(self, self.reference)
        return value

    async def reserve(self, body, create, allowance):
        self._live()
        self.client.validate_create(create, body)
        self.lease.mark_dispatch(self, 'reserve')
        try:
            value = await self.client.reserve(self.client_uuid, body, allowance, create_body=create)
        except CoordinatorError as error:
            if error.code != 'invalid_request' or error.uncertain:
                raise
            # Explicit collision exception: the retry identity is durable before send,
            # with a bug signal; never replay create/exec or allocate an invisible UUID.
            self._live()
            self.client_uuid = str(uuid4())
            self.reference = self.client_uuid
            self.lease.record_coordinator(self, coordinator_lease_id=self.client_uuid, reserve_collision=True)
            value = await self.client.reserve(self.client_uuid, body, allowance, create_body=create)
        return self._observe(value)

    async def create(self, body, allowance):
        self._live()
        self.lease.mark_dispatch(self, 'create')
        return self._observe(await self.client.create(self.client_uuid, body, allowance))

    async def status(self, allowance):
        try:
            return self._observe(await self.client.status(self.client_uuid, allowance))
        except BaseException:
            self.lease.fence()
            raise

    async def admit(self, reserve, create, allowance):
        try:
            await self.reserve(reserve, create, allowance)
            await self.create(create, allowance)
            while True:
                value = await self.status(allowance)
                if value['flags']['fenced'] or value['flags']['expired']:
                    raise TransportError('lease_not_ready', uncertain=True)
                if value['flags']['ready']:
                    return value
                await allowance.run(lambda: asyncio.sleep(.02))
        except TransportError as error:
            if error.uncertain or self.lease._entry.get('create_sent_at') is not None:
                await self.reconcile(allowance)
            raise
        except BaseException:
            self.lease.fence()
            raise

    async def reconcile(self, allowance):
        """No adoption or replay. Status is diagnostic; kill and full LIST prove cleanup."""
        self.lease.fence()
        try:
            await self.status(allowance)
        except TransportError:
            pass
        await self.release(allowance)

    async def dispatch(self, request, allowance, *, stream_allowance, output_cap_bytes, message_cap):
        self._live()
        if stream_allowance is None:
            raise TransportError('invalid_bound')
        value = await self.status(allowance)
        if (value['flags']['fenced'] or value['flags']['expired'] or not value['flags']['ready']):
            await self.reconcile(allowance)
            raise TransportError('lease_not_ready', uncertain=True)
        if self.exec_channel is None:
            raise TransportError('stock_exec_unavailable')
        self.lease.mark_dispatch(self, 'execute')
        self._exec = self.exec_channel.bind_lease(self.client_uuid, self.sandbox_id,
                                                local_owner_id=self.lease.owner_id)
        return JournalStream(self, request, stream_allowance, output_cap_bytes, message_cap)

    async def kill(self, allowance):
        self.lease.fence()
        if self._exec is not None:
            self._exec.invalidate()
        try:
            return await self._kill_barrier(allowance)
        except TransportError:
            # KILL is idempotent. A lost reply never means release: observe, kill
            # again, then require a complete inventory within the same allowance.
            try:
                await self.status(allowance)
            except TransportError:
                pass
            reference = await self._kill_barrier(allowance)
            await self._confirm_inventory(allowance)
            return reference

    async def _kill_barrier(self, allowance):
        value = self._observe(await self.client.kill(self.client_uuid, allowance))
        while not value['flags']['barrier_confirmed']:
            await allowance.run(lambda: asyncio.sleep(.02))
            value = await self.status(allowance)
        self.lease.note_killed()
        return self.reference

    async def list_owned(self, allowance):
        self.inventory = await self.client.list_owned(allowance)
        pairs = outstanding(self.inventory)
        # Collision retries still belong to the original locked local journal.
        return tuple((ref, self.lease.lease_id if ref == self.client_uuid else local)
                     for ref, local in pairs)

    async def release(self, allowance):
        await self.kill(allowance)
        await self._confirm_inventory(allowance)
        # Never clear here: driver/reaper combines its own proofs under the lock.

    async def _confirm_inventory(self, allowance):
        pairs = await self.list_owned(allowance)
        if any(local == self.lease.lease_id for _, local in pairs):
            raise TransportError('sandbox_placement_release_unconfirmed', uncertain=True)
        # Never clear here: driver/reaper combines its own proofs under the lock.


class JournalStream:
    """Split dispatch/wait around stock's one bounded exec coroutine."""
    def __init__(self, session, request, allowance, output_cap_bytes, message_cap):
        self.session = session
        async def execute():
            session._live()
            return await session._exec.execute(
                request, allowance, attempt=1, output_cap_bytes=output_cap_bytes, message_cap=message_cap)
        self._task = asyncio.create_task(execute())

    def cancel(self):
        self.session.lease.fence()
        self.session._exec.invalidate()
        self._task.cancel()

    async def wait(self, wait_s):
        self.session._live()
        done, _ = await asyncio.wait((self._task,), timeout=wait_s)
        self.session._live()
        if not done:
            return None
        try:
            return self._task.result()
        except BaseException:
            self.session.lease.fence()
            raise


class ReaperAdapter(JournalReapingBackend):
    """RPC tasks receive snapshots, never a journal fd that outlives its lock."""
    def __init__(self, client, *, loop, owner_id):
        self.client, self._loop, self._owner = client, loop, owner_id
        self._pid = os.getpid()
        if owner_id != client.local_owner_id:
            raise TransportError('journal_owner_mismatch', uncertain=True)
        refuse_fork_entries()
        self.inventory = ()
        self._local_ids = {}

    def validate_reaper_context(self):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if (running is not None or self._pid != os.getpid()
                or self._loop.is_closed() or not self._loop.is_running()):
            raise ValueError('journal bridge requires an external thread and a running loop')

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
        except TransportError as error:
            raise PlacementUnavailable(error.code) from None

    def kill_journaled(self, owner_id, lease_id, entry, bound):
        if owner_id != self._owner or not _valid_entry(entry, lease_id):
            raise ValueError('invalid lease journal')
        identity = entry.get('coordinator_lease_id')
        if not identity:
            raise ForkJournalRefusal()
        self._local_ids[identity] = lease_id
        async def kill():
            a = CallerAllowance(bound)
            try:
                value = await self.client.status(identity, a)
                if entry.get('coordinator_sandbox_id') not in (None, value['sandbox_id']):
                    raise TransportError('generation_mismatch', uncertain=True)
            except TransportError:
                # Unknown, unavailable and lost status replies grant no adoption;
                # kill is still safe and required for this journaled identity.
                pass
            value = await self.client.kill(identity, a)
            while not value['flags']['barrier_confirmed']:
                await a.run(lambda: asyncio.sleep(.02))
                value = await self.client.status(identity, a)
            if entry.get('coordinator_sandbox_id') not in (None, value['sandbox_id']):
                raise TransportError('generation_mismatch', uncertain=True)
            return identity
        return self._run(kill(), bound)

    def list_owned(self, owner_id, bound):
        if owner_id != self._owner:
            raise ValueError('journal owner mismatch')
        async def listing():
            values = await self.client.list_owned(CallerAllowance(bound))
            return values
        self.inventory = self._run(listing(), bound)
        return tuple((ref, self._local_ids.get(ref, local))
                     for ref, local in outstanding(self.inventory))


class OpenShellCleanupBackend(ReaperAdapter):
    """Cleanup-only bridge; deliberately distinct from the executing backend."""
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
