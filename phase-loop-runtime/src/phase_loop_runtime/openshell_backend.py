"""Unregistered finite implementation integration; production construction is closed.

Injected adapters are trusted runtime code, never objects reconstructed from worker
claims. Model mode exercises lifecycle wiring, not ExecutingBackend conformance:
endpoint expiry, materialization, isolation and provenance remain unqualified.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Protocol

from .openshell_artifacts import Bound, Identity, Refused, SourceBundle, canonical, digest, validate_result
from .openshell_journal import JournalSession, ReaperAdapter
from .openshell_transport import CallerAllowance, CoordinatorError, TransportError, UnsupportedCapability
from .placement_contract import coordinator_code
from .openshell_worker import preflight_worker, seal_request, unwrap_worker_result
from .executable_dependency_startup import refuse_unwired_dependency_route
from .executable_dependency import ExecutableDependencyError
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

    def __init__(self, client, exec_channel, *, loop, workspace: str, owner_id: str,
                 bundle: SourceBundle, stage: StageAdapter, worker: WorkerAdapter,
                 task: str, tests: tuple[str, ...], login_store, request_cap: int,
                 message_cap: int, quarantine: Path, model_only: bool = False, ttl_s: int = 3600):
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
        if type(ttl_s) is not int or not 1 <= ttl_s <= 3600:
            raise Refused("invalid_ttl")
        self._ttl = ttl_s
        self._expiry = self._renew_at = self._life_end = None
        self._bridge = ReaperAdapter(client, loop=loop, owner_id=owner_id)
        self._bridge.validate_reaper_context()
        self._client, self._exec_channel = client, exec_channel
        self._workspace, self._owner = workspace, owner_id
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
            self._session = JournalSession(lease, self._client, self._exec_channel)
            self._life_end = time.monotonic() + max(0, 86400 - max(0, time.time() - lease._entry['created_at']))
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
                raise PlacementUnavailable(_TIMEOUT, uncertain=True) from None
            raise

    def admit(self, request, bound):
        session = self._request(request)  # finite deadline refusal before CREATE
        try:
            refuse_unwired_dependency_route("openshell")
            create = self._worker.create_request()
            preflight_worker(self._bundle, create, task=self._task, tests=self._tests,
                             deadline_s=request.deadline_s, request_cap=self._request_cap,
                             generation=session.reference, exec_request=self._worker.exec_request)
        except (ValueError, ExecutableDependencyError) as error:
            raise PlacementUnavailable("sandbox_placement_refused", str(error), uncertain=False) from None

        async def admit():
            allowance = CallerAllowance(bound)
            reserve = dict(workload=request.workload, ttl_s=self._ttl,
                           image_digest=create['image'].rsplit('@', 1)[-1],
                           policy_digest=create['policy_digest'])
            try:
                observed = await session.admit(reserve, create, allowance)
            except TransportError as error:
                raise self._placement_error(error, 'reserve' if session.lease._entry.get(
                    'create_sent_at') is None else 'create') from None
            self._track_expiry(observed)
            self._binding = StageBinding(self._workspace, self._owner, request.lease_id,
                                         session.reference, self._bundle.sha256)

        return self._run(admit(), bound)

    @staticmethod
    def _placement_error(error, phase):
        uncertain = error.uncertain or error.code == 'unavailable' and phase != 'reserve'
        if uncertain:
            code = ('sandbox_placement_release_unconfirmed' if error.code == 'duplicate_binding'
                    else _TIMEOUT)
        elif error.code == 'unavailable' and phase == 'reserve':
            code = 'sandbox_placement_unreachable'
        elif error.code.startswith('sandbox_placement_'):
            code = error.code
        elif isinstance(error, CoordinatorError):
            code = coordinator_code(error.code) or 'sandbox_placement_refused'
        else:
            code = 'sandbox_placement_refused'
        refusal = PlacementUnavailable(code, getattr(error, 'reason', None),
                                       uncertain=uncertain)
        return refusal

    def _track_expiry(self, value):
        now = time.monotonic()
        expiry = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
        self._expiry = min(self._life_end, now + self._ttl, now + max(0, (
            expiry - datetime.now(timezone.utc)).total_seconds()))
        self._renew_at = now + max(0, self._expiry - now) / 2

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
                    any(type(value) is not str for value in (
                        receipt.workspace, receipt.owner_id, receipt.lease_id,
                        receipt.generation, receipt.source_sha256)) or
                    self._binding != receipt):
                session.lease.fence()
                raise Refused("stage_binding_mismatch")
            session.lease.confirm_commit_ref(session, self._binding.generation)
            self._committed = True
            return BackendReceipt("committed", self._binding.generation, self._binding.source_sha256)

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
        return Bound(min(self._end, self._expiry, self._life_end), lambda: self._cancelled.is_set() or
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
        self._end = min(self._end, self._life_end, time.monotonic() + spec.must_end_within_s)
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
                wire, CallerAllowance(bound), stream_allowance=CallerAllowance(
                    OperationBound(self._result_bound().check(), _LiveCancellation(self))),
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
        artifact, evidence = unwrap_worker_result(raw.stdout, self._bundle, self._identity)
        self._worker.validate_native(self._identity, artifact, self._result_bound())
        patch = validate_result(self._identity, artifact, self._bundle,
                                self._quarantine, self._result_bound())
        # Worker identity hashes canonical credential-free metadata. C9 hashes the
        # exact secret-bearing request bytes. Never substitute one for the other.
        result_value = {"request_sha256": self._wire_digest,
                        "worker_request_sha256": self._identity.request_sha256,
                        "quarantine": str(patch.path), "patch_sha256": patch.sha256,
                        "required_next_step": patch.required_next_step}
        if evidence is not None:
            # Never treat echoed reclaims as coordinator authority. Observation was
            # validated and retained by SL-2; worker evidence stays client-reported.
            evidence["reclaims"] = self._session.observation.get("reclaims", [])
            self._result_bound().check()
            record = canonical(evidence)
            path = self._quarantine / "worker-evidence.json"
            with path.open("xb") as stream:
                stream.write(record)
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(self._quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            result_value.update(worker_evidence=evidence, worker_evidence_path=str(path),
                                worker_evidence_sha256=digest(record))
        result = canonical(result_value)
        self._result_bound().check()
        if len(result) > self._bundle.limits.output_bytes:
            raise Refused("result_limit")
        return ExecResult(sandbox_ref, 0, result, False)

    def kill(self, lease_id, bound):
        if self._session is None or lease_id != self._session.lease.lease_id:
            raise Refused("lease_binding_invalid")
        self._session.lease.fence()
        return self._run(self._session.kill(CallerAllowance(bound)), bound, cleanup=True)

    def cancel(self, sandbox_ref, bound):
        if self._binding is None or sandbox_ref != self._binding.generation:
            raise Refused("generation_mismatch")
        return self.kill(self._session.lease.lease_id, bound)

    def list_owned(self, owner_id, bound):
        if owner_id != self._owner or self._session is None:
            raise Refused("owner_mismatch")
        return self._run(self._session.list_owned(CallerAllowance(bound)), bound, cleanup=True)

    def release(self, prepared, bound=None):
        if bound is None:
            raise UnsupportedCapability()
        return self._run(self._session.release(CallerAllowance(bound)), bound, cleanup=True)

    def renew(self, sandbox_ref, until_s, bound):
        session = self._live()
        if sandbox_ref != session.reference or type(until_s) not in (int, float) or not math.isfinite(until_s):
            raise Refused('invalid_renew')
        now = time.monotonic()
        if now >= self._expiry or now >= self._life_end:
            session.lease.fence()
            raise PlacementUnavailable(_END_REACHED)
        if now < self._renew_at:
            return  # Existing authoritative expiry still covers the half-TTL window.
        extend = min(self._ttl, 3600, math.floor(until_s), math.floor(self._life_end - now))
        if extend < 1:
            session.lease.fence()
            raise PlacementUnavailable(_END_REACHED)

        async def renew():
            allowance = CallerAllowance(bound)
            try:
                observed = await self._client.renew(session.client_uuid, extend, allowance)
                session._observe(observed)
                if observed['flags']['expired'] or observed['flags']['fenced']:
                    raise TransportError('lease_not_ready', uncertain=True)
                self._track_expiry(observed)
            except TransportError as error:
                if error.code == 'lifetime_exceeded':
                    # End the fixed execution window before the last known expiry.
                    self._end = min(self._end or self._expiry, self._expiry)
                await session.reconcile(allowance)
                raise self._placement_error(error, 'renew') from None
        return self._run(renew(), bound)
