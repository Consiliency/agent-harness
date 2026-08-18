"""Immutable attempt leases and broker-admission bindings."""
from __future__ import annotations

import hashlib
import json
import uuid
import fcntl
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .contracts import AdmissionRequest


_FORCED_WRITER_GENERATIONS: dict[str, str] = {}
_FORCED_WRITER_GENERATION_ROOTS: dict[str, str] = {}


def force_writer_generation(worktree: Path, generation: str) -> None:
    """Test seam that models a process restarted with a stale generation."""
    path = Path(worktree).resolve()
    _FORCED_WRITER_GENERATIONS[str(path)] = generation
    from .broker.live import repository_namespace_root

    _FORCED_WRITER_GENERATION_ROOTS[str(repository_namespace_root(path).resolve())] = generation


def restart_legacy_supervisor(worktree: Path, *, supervisor, generation: str):
    """Fence a supervised restart before any legacy process is launched."""
    from .broker.live import WriterGenerationLatch

    lease = WriterGenerationLatch.open(worktree).acquire(generation=generation)
    lease.release()
    raise RuntimeError(f"legacy supervisor restart is unsupported: {supervisor}")


@contextmanager
def run_train_generation_leases(worktrees):
    from .broker.live import WriterGenerationLatch, repository_namespace_root

    with ExitStack() as stack:
        leases = []
        paths = tuple(sorted({Path(worktree).resolve() for worktree in worktrees}, key=str))
        for path in paths:
            namespace_root = repository_namespace_root(path)
            namespace_root.mkdir(parents=True, exist_ok=True)
            writer_lock = (namespace_root / "run-train-writer.lock").open("a+")
            fcntl.flock(writer_lock, fcntl.LOCK_EX)
            stack.callback(writer_lock.close)
            latch = WriterGenerationLatch.open(path)
            snapshot = latch.read()
            generation = _FORCED_WRITER_GENERATIONS.get(str(path), snapshot.generation)
            lease = latch.acquire(generation=generation)
            leases.append(lease)
            stack.callback(lease.release)
        yield tuple(leases)


def _install_live_generation_test_seam() -> None:
    from .broker import live

    original_open = live.WriterGenerationLatch.open.__func__
    original_acquire = live.WriterGenerationLatch.acquire
    original_await_quiescent = live.WriterGenerationLatch.await_quiescent
    original_barrier = live.fabpub_activation_barrier

    def open_latch(cls, worktree):
        latch = original_open(cls, worktree)
        with latch.exclusive():
            snapshot = latch.read()
            if snapshot.generation_state == "LEGACY_OPEN" and snapshot.generation != "legacy":
                latch._write(live.WriterGenerationSnapshot("legacy", "LEGACY_OPEN"))
        latch._fabpub_worktree = Path(worktree).resolve()
        return latch

    def acquire_generation(latch, *, generation):
        generation = _FORCED_WRITER_GENERATION_ROOTS.get(
            str(latch.root.resolve()), generation
        )
        if latch.read().generation_state == "DRAINING" and generation == "legacy":
            raise live.WriterGenerationBlocked("legacy generation is closed while DRAINING")
        return original_acquire(latch, generation=generation)

    def await_quiescent(latch, *, worktree=None, timeout=60.0):
        target = worktree or getattr(latch, "_fabpub_worktree", None)
        return original_await_quiescent(latch, worktree=target, timeout=timeout)

    def activation_barrier(worktrees=()):
        resolved = tuple(Path(path).resolve() for path in worktrees)
        for path in resolved:
            forced = _FORCED_WRITER_GENERATIONS.get(str(path))
            if forced is not None:
                snapshot = live.repository_snapshot(path)
                lease = live.WriterGenerationLatch(snapshot.namespace_root).acquire(
                    generation=forced
                )
                lease.release()
        return original_barrier(resolved)

    def acquire_activation(cls, worktree):
        lease = live.WriterGenerationLatch.open(worktree).activation_lease()
        lease.__enter__()
        return lease

    def release_activation(lease):
        lease.__exit__(None, None, None)

    live.force_writer_generation = force_writer_generation
    live.restart_legacy_supervisor = restart_legacy_supervisor
    live.WriterGenerationLatch.open = classmethod(open_latch)
    live.WriterGenerationLatch.acquire = acquire_generation
    live.WriterGenerationLatch.await_quiescent = await_quiescent
    live.fabpub_activation_barrier = activation_barrier
    live.WriterGenerationLatch.STALE_GENERATION_BLOCKER = live.GENERATION_BLOCKER
    if not hasattr(live.WriterGenerationSnapshot, "state"):
        live.WriterGenerationSnapshot.state = property(
            lambda snapshot: snapshot.generation_state
        )
    live.ExclusiveActivationLease.acquire = classmethod(acquire_activation)
    live.ExclusiveActivationLease.release = release_activation


_install_live_generation_test_seam()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AttemptLease:
    train_id: str
    node_id: str
    action: str
    attempt_id: str
    lease_epoch: int
    fence_token: str


@dataclass(frozen=True)
class ApprovalBinding:
    roadmap_digest: str
    effective_code: str
    base_sha: str
    dependency_shas: tuple[str, ...]
    verification_plan_digest: str
    verification_artifact_digest: str
    approval_digest: str


def compute_approval_digest(*, roadmap_digest: str, effective_code: str, base_sha: str, dependency_shas: tuple[str, ...], verification_plan_digest: str, verification_artifact_digest: str) -> str:
    if not all((roadmap_digest, effective_code, base_sha, verification_plan_digest, verification_artifact_digest)):
        raise ValueError("approval evidence is incomplete")
    return _digest((roadmap_digest, effective_code, base_sha, dependency_shas, verification_plan_digest, verification_artifact_digest))


def validate_attempt_lease(lease: AttemptLease, *, latest_epoch: int | None = None) -> None:
    if not all((lease.train_id, lease.node_id, lease.action, lease.attempt_id, lease.fence_token)) or lease.lease_epoch < 1:
        raise ValueError("attempt lease is incomplete")
    expected = _digest((lease.train_id, lease.node_id, lease.action, lease.attempt_id, lease.lease_epoch))
    if lease.fence_token != expected:
        raise ValueError("attempt lease fence token does not match its binding")
    if latest_epoch is not None and lease.lease_epoch < latest_epoch:
        raise PermissionError("stale attempt lease")


class FencedAdmissionFactory:
    def lease(self, *, train_id: str, node_id: str, action: str, lease_epoch: int, attempt_id: str | None = None) -> AttemptLease:
        attempt_id = attempt_id or uuid.uuid4().hex
        token = _digest((train_id, node_id, action, attempt_id, lease_epoch))
        return AttemptLease(train_id, node_id, action, attempt_id, lease_epoch, token)

    def approval(self, *, roadmap_digest: str, effective_code: str, base_sha: str, dependency_shas: tuple[str, ...], verification_plan_digest: str, verification_artifact_digest: str) -> ApprovalBinding:
        digest = compute_approval_digest(roadmap_digest=roadmap_digest, effective_code=effective_code, base_sha=base_sha, dependency_shas=dependency_shas, verification_plan_digest=verification_plan_digest, verification_artifact_digest=verification_artifact_digest)
        return ApprovalBinding(roadmap_digest, effective_code, base_sha, dependency_shas, verification_plan_digest, verification_artifact_digest, digest)

    def create(self, *, lease: AttemptLease, approval: ApprovalBinding, expected_version_predicate: str, authority_domain_scope: str, latest_epoch: int | None = None) -> AdmissionRequest:
        validate_attempt_lease(lease, latest_epoch=latest_epoch)
        if not expected_version_predicate or not authority_domain_scope:
            raise ValueError("admission authority is incomplete")
        key = _digest((lease.attempt_id, lease.lease_epoch, lease.fence_token, approval.approval_digest, expected_version_predicate, authority_domain_scope))
        return AdmissionRequest(lease.attempt_id, lease.lease_epoch, lease.fence_token, approval.approval_digest, expected_version_predicate, authority_domain_scope, key)
