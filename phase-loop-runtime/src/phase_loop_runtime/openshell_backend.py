"""Unregistered finite implementation integration; production construction is closed.

Injected adapters are trusted runtime code, never objects reconstructed from worker
claims. Model mode exercises lifecycle wiring, not ExecutingBackend conformance:
endpoint expiry, materialization, isolation and provenance remain unqualified.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError
from dataclasses import dataclass
import math
from pathlib import Path
import secrets
import threading
import time
from typing import Protocol

from .openshell_artifacts import Bound, Identity, Refused, SourceBundle, canonical, digest, validate_result
from .openshell_journal import JournalSession, ReaperAdapter
from .openshell_transport import UnsupportedCapability
from .openshell_worker import seal_request
from .placement_lease import LiveLeaseBackend
from .sandbox_placement import (
    BackendReceipt, Declaration, ExecProgress, ExecResult, ExecSpec, OperationBound,
    PlacementUnavailable, _END_REACHED, _TIMEOUT,
)


@dataclass(frozen=True)
class StageBinding:
    workspace: str
    owner_id: str
    lease_id: str
    generation: str
    source_sha256: str


class StageAdapter(Protocol):
    """Must atomically publish verified source under the lease's cleanup obligation.

    Cancellation prevents publication; uncertainty never permits replay. A real
    implementation must own bounded partial-state cleanup and endpoint fixed ends.
    """
    def validate_configuration(self) -> None: ...

    async def commit(self, binding: StageBinding, bundle: SourceBundle,
                     bound: OperationBound) -> StageBinding: ...


class WorkerAdapter(Protocol):
    """Installed runtime mapping and independent native evidence validation.

    Validation must cover immutable image/program, isolation, channel provenance,
    and native completion from trusted runtime inputs. No adapter is provided here.
    Model fixtures explicitly cannot establish those production properties.
    """
    image_sha256: str

    def validate_configuration(self) -> None: ...

    def create_request(self): ...

    def exec_request(self, wire: bytes, end_s: float): ...

    def validate_native(self, identity: Identity, envelope: bytes, bound: Bound) -> None: ...


class _LiveCancellation:
    def __init__(self, backend):
        self.backend = backend

    def is_set(self):
        backend = self.backend
        return (backend._cancelled.is_set() or not backend._session.lease.held or
                backend._session.lease.fenced)


def _observe_task(task):
    # Consume late exceptions without logging remote exception chains or payloads.
    if not task.cancelled():
        task.exception()


class OpenShellBackend(LiveLeaseBackend):
    """Single-use driver adapter on an injected dedicated loop, model-only for now.

    Does not own the channel/loop, register itself, enroll an owner, recover a live
    handle or claim physical conformance. Use ReaperAdapter separately for recovery.
    """
    name = "openshell-model"

    def __init__(self, proto, stub, *, loop, workspace: str, owner_id: str,
                 bundle: SourceBundle, stage: StageAdapter, worker: WorkerAdapter,
                 task: str, tests: tuple[str, ...], login_store, request_cap: int,
                 message_cap: int, quarantine: Path, model_only: bool = False):
        if model_only is not True:
            raise Refused("production_adapters_unqualified")
        if stage is None or worker is None:
            raise Refused("required_adapter_unavailable")
        stage.validate_configuration()
        worker.validate_configuration()
        bundle.validate()
        if (type(request_cap) is not int or request_cap <= 0 or
                type(message_cap) is not int or message_cap <= 0):
            raise Refused("invalid_caps")
        self._bridge = ReaperAdapter(proto, stub, loop=loop, workspace=workspace, owner_id=owner_id)
        self._bridge.validate_reaper_context()
        self._proto, self._stub, self._workspace, self._owner = proto, stub, workspace, owner_id
        self._bundle, self._stage, self._worker = bundle, stage, worker
        self._task, self._tests, self._login_store = task, tests, login_store
        self._request_cap, self._message_cap, self._quarantine = request_cap, message_cap, quarantine
        self._session = None
        self._binding = None
        self._committed = False
        self._commit_attempted = False
        self._sealed = False
        self._executed = False
        self._stream = None
        self._identity = None
        self._wire_digest = None
        self._end = None
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def capabilities(self):
        return frozenset()  # No C5 qualification is supplied by the model.

    def declaration(self):
        return Declaration()

    def available(self, request):
        return (request.workload == "implementation" and
                type(request.deadline_s) in (int, float) and
                math.isfinite(request.deadline_s) and request.deadline_s > 0 and
                request.snapshot_sha256 == self._bundle.sha256)

    def endpoint(self, root):
        return None  # Explicit in-process model; no production endpoint constructor.

    def bind_live_lease(self, lease):
        self._bridge.validate_reaper_context()
        with self._lock:
            if self._session is not None or lease.owner_id != self._owner:
                raise Refused("lease_binding_invalid")
            self._session = JournalSession(lease, self._proto, self._stub, workspace=self._workspace)
            return self._session

    def _live(self):
        if self._session is None:
            raise Refused("lease_unbound")
        self._session.lease.validate_live_binding(self._session)
        if self._cancelled.is_set():
            raise Refused("cancelled")
        return self._session

    def _request(self, request):
        session = self._live()
        if (not self.available(request) or request.owner_id != self._owner or
                request.lease_id != session.lease.lease_id):
            raise Refused("request_binding_invalid")
        return session

    def _run(self, coroutine, bound, *, cleanup=False):
        # Unlike a blocking future.result(timeout), this observes cancellation while
        # a stage adapter is suspended. Late coroutine results never grant ownership.
        tasks = []
        stop = threading.Event()

        async def observed():
            task = asyncio.current_task()
            tasks.append(task)
            task.add_done_callback(_observe_task)
            if stop.is_set():
                coroutine.close()
                raise asyncio.CancelledError()
            return await coroutine

        def cancel_task():
            if tasks:
                tasks[0].cancel()

        try:
            self._bridge.validate_reaper_context()
            if bound is None:
                raise UnsupportedCapability()
            end = Bound(time.monotonic() + bound.timeout_s, bound.cancelled.is_set)
            end.check()
            future = asyncio.run_coroutine_threadsafe(observed(), self._bridge._loop)
        except BaseException:
            coroutine.close()
            raise
        try:
            while True:
                left = end.check()
                try:
                    result = future.result(timeout=min(left, 0.02))
                    end.check()
                    return result
                except TimeoutError:
                    if future.done():
                        return future.result()
        except BaseException as exc:
            stop.set()
            self._bridge._loop.call_soon_threadsafe(cancel_task)
            if not cleanup:
                self._session.lease.fence()
            if isinstance(exc, Refused) and str(exc) == "end_reached":
                raise PlacementUnavailable(_TIMEOUT) from None
            raise

    def admit(self, request, bound):
        session = self._request(request)  # finite deadline refusal before CREATE

        async def admit():
            end = Bound(time.monotonic() + bound.timeout_s, bound.cancelled.is_set)
            await session.create(self._worker.create_request(), OperationBound(end.check(), bound.cancelled))
            while True:
                self._live()
                observed = await session.status(OperationBound(end.check(), bound.cancelled))
                if observed.admission_ready:
                    self._binding = StageBinding(self._workspace, self._owner, request.lease_id,
                                                 observed.sandbox_ref, self._bundle.sha256)
                    return
                await asyncio.sleep(min(0.02, end.check()))

        return self._run(admit(), bound)

    def commit(self, prepared, request, bound=None):
        session = self._request(request)
        if prepared.snapshot_sha256 != self._bundle.sha256 or self._binding is None:
            raise Refused("source_binding_invalid")
        with self._lock:
            if self._commit_attempted:
                raise Refused("commit_not_repeatable")
            self._commit_attempted = True

        async def commit():
            receipt = await self._stage.commit(self._binding, self._bundle, bound)
            self._live()
            if (bound.cancelled.is_set() or type(receipt) is not StageBinding or
                    self._binding != receipt):
                session.lease.fence()
                raise Refused("stage_binding_mismatch")
            session.lease.confirm_commit_ref(session, receipt.generation)
            self._committed = True
            return BackendReceipt("committed", receipt.generation, receipt.source_sha256)

        return self._run(commit(), bound)

    def seal(self, request):
        self._request(request)
        with self._lock:
            if not self._committed or self._sealed:
                raise Refused("seal_not_permitted")
            self._sealed = True
        # Counting from before sealing shortens, never extends, the client end.
        self._end = time.monotonic() + request.deadline_s
        identity, wire = seal_request(
            self._bundle, nonce=secrets.token_hex(32), generation=self._binding.generation,
            image_sha256=self._worker.image_sha256, task=self._task, tests=self._tests,
            must_end_within_s=request.deadline_s, login_store=self._login_store(),
            request_cap=self._request_cap)
        self._live()
        self._identity, self._wire_digest = identity, digest(wire)
        return ExecSpec("implementation", wire, request.deadline_s,
                        self._result_bound().check(), self._bundle.limits.output_bytes)

    def _result_bound(self):
        return Bound(self._end, lambda: self._cancelled.is_set() or
                     not self._session.lease.held or self._session.lease.fenced)

    def execute(self, sandbox_ref, spec, bound):
        session = self._live()
        with self._lock:
            if (self._executed or self._identity is None or sandbox_ref != self._binding.generation or
                    spec.workload != "implementation" or digest(spec.request) != self._wire_digest or
                    spec.deadline_s is None or spec.must_end_within_s is None or
                    not math.isfinite(spec.must_end_within_s) or spec.must_end_within_s <= 0 or
                    spec.output_cap_bytes != self._bundle.limits.output_bytes):
                raise Refused("execute_not_permitted")
            self._executed = True
        self._end = min(self._end, time.monotonic() + spec.must_end_within_s)
        self._cancelled = bound.cancelled

        async def execute():
            left = self._result_bound().check()
            wire = self._worker.exec_request(spec.request, left)
            timeout = wire.execution_timeout.seconds + wire.execution_timeout.nanos / 1e9
            if (wire.stdin != spec.request or wire.environment or not wire.command or
                    not wire.workdir.startswith("/") or not wire.no_login_shell or wire.tty or
                    not 0 < timeout <= left):
                raise Refused("worker_mapping_invalid")
            self._stream = await session.dispatch(
                wire, bound, stream_bound=OperationBound(self._result_bound().check(), _LiveCancellation(self)),
                output_cap_bytes=spec.output_cap_bytes, message_cap=self._message_cap)
            self._stream._task.add_done_callback(_observe_task)
            self._live()
            return BackendReceipt("launched", sandbox_ref, self._bundle.sha256)

        return self._run(execute(), bound)

    def wait(self, sandbox_ref, wait_s):
        self._live()
        if self._stream is None or sandbox_ref != self._binding.generation:
            raise Refused("stream_unavailable")
        try:
            remaining = self._result_bound().check()
        except Refused as exc:
            if str(exc) == "end_reached":
                raise PlacementUnavailable(_END_REACHED) from None
            raise
        raw = self._run(self._stream.wait(min(wait_s, remaining)),
                        OperationBound(min(wait_s + 0.1, remaining), self._cancelled))
        self._result_bound().check()
        if raw is None:
            return ExecProgress(sandbox_ref, 0)  # No invented progress.
        if raw.exit_code != 0 or raw.stderr:
            raise Refused("worker_incomplete")
        self._worker.validate_native(self._identity, raw.stdout, self._result_bound())
        patch = validate_result(self._identity, raw.stdout, self._bundle,
                                self._quarantine, self._result_bound())
        # Worker identity hashes canonical credential-free metadata. C9 hashes the
        # exact secret-bearing request bytes. Never substitute one for the other.
        result = canonical({"request_sha256": self._wire_digest,
                            "worker_request_sha256": self._identity.request_sha256,
                            "quarantine": str(patch.path), "patch_sha256": patch.sha256,
                            "required_next_step": patch.required_next_step})
        self._result_bound().check()
        if len(result) > self._bundle.limits.output_bytes:
            raise Refused("result_limit")
        return ExecResult(sandbox_ref, 0, result, False)

    def kill(self, lease_id, bound):
        if self._session is None or lease_id != self._session.lease.lease_id:
            raise Refused("lease_binding_invalid")
        self._session.lease.fence()
        return self._run(self._session.kill(bound), bound, cleanup=True)

    def cancel(self, sandbox_ref, bound):
        if self._binding is None or sandbox_ref != self._binding.generation:
            raise Refused("generation_mismatch")
        return self.kill(self._session.lease.lease_id, bound)

    def list_owned(self, owner_id, bound):
        if owner_id != self._owner or self._session is None:
            raise Refused("owner_mismatch")
        return self._run(self._session.list_owned(bound), bound, cleanup=True)

    def release(self, prepared, bound=None):
        if bound is None:
            raise UnsupportedCapability()
        end = Bound(time.monotonic() + bound.timeout_s, bound.cancelled.is_set)
        self.kill(self._session.lease.lease_id, OperationBound(end.check(), bound.cancelled))
        owned = self.list_owned(self._owner, OperationBound(end.check(), bound.cancelled))
        if any(lease == self._session.lease.lease_id for _, lease in owned):
            raise Refused("release_unconfirmed")
        # Only the driver/reaper clears the journal after its own complete LIST.

    def renew(self, sandbox_ref, until_s, bound):
        raise UnsupportedCapability()
