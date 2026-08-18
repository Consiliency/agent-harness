"""Durable, metadata-only broker admission ordering."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from phase_loop_runtime.convergence.contracts import AdmissionRequest


@dataclass(frozen=True)
class AdmissionRecord:
    sequence: int
    epoch: int
    request: AdmissionRequest


BrokerAdmissionPolicy = Callable[[AdmissionRequest], bool]


def _fabpub_active() -> bool:
    """Activation probe that never downgrades on a configuration failure."""
    from .live import fabpub_capability_active

    return fabpub_capability_active()


#: "The caller declared no lease at all", distinct from an explicit
#: ``generation_lease=None``.  A DECLARED absence is denied under an ACTIVE
#: generation; an undeclared one is validated against latch state only, because
#: the frozen compatibility helpers construct stores without the argument.
_UNDECLARED = object()


class LinearizableAdmissionStore:
    """Append-only admission log guarded by an OS advisory lock."""
    def __init__(
        self,
        root: Path,
        policy: BrokerAdmissionPolicy | None = None,
        epoch_blocked: Callable[[], bool] | None = None,
        generation_lease=_UNDECLARED,
    ) -> None:
        self.root, self.policy, self.epoch_blocked = root, policy, epoch_blocked or (lambda: False)
        # The FABPUB WriterGenerationLease.v1 this store writes under.  It is
        # revalidated by exact nonce inside the store lock before every append.
        self.generation_lease = generation_lease
        # SL1-SOL-07: while FABPUB is active the canonical tree is NOT created at
        # construction.  Materializing an unauthenticated namespace is itself
        # state a later inventory must treat as unattested, so the directory is
        # created only once `_authorize` has proved receipt + generation.
        if not _fabpub_active():
            self.root.mkdir(parents=True, exist_ok=True)
        self.path, self.lock_path = root / "admissions.jsonl", root / "admissions.lock"

    def _authorize(self) -> None:
        """Authenticate BEFORE any directory creation, then create the tree."""
        from .live import REPOSITORY_NAMESPACE_DIR, authenticated_partition_floor

        self._require_generation()
        canonical_store = (
            self.root.parent.name == "repositories"
            and self.root.parent.parent.name == REPOSITORY_NAMESPACE_DIR
        )
        if _fabpub_active() and (
            self.generation_lease is not _UNDECLARED or canonical_store
        ):
            # An activated canonical store is routable only behind an armed,
            # authenticated partition receipt.  This raises when absent.
            authenticated_partition_floor(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _require_generation(self) -> None:
        """In-lock generation revalidation; closes the check/use race."""
        from .live import require_current_generation

        lease = self.generation_lease
        if lease is _UNDECLARED:
            require_current_generation(self.root, None, strict=False)
        else:
            require_current_generation(self.root, lease, strict=True)

    def _records(self) -> list[AdmissionRecord]:
        if not self.path.exists(): return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line); raw["request"] = AdmissionRequest(**raw["request"]); records.append(AdmissionRecord(**raw))
        return records

    def _canonical_high_water(self, records: list[AdmissionRecord]) -> int:
        """The canonical floor: ``max(record.epoch)``, or 0 when none exists."""
        return max((record.epoch for record in records), default=0)

    def admit_next(
        self,
        make_request: Callable[[int, str], AdmissionRequest],
        *,
        attempt_id: str,
        precondition: Callable[[], bool],
    ) -> AdmissionRecord:
        """Allocate the next repository-wide epoch and append one record.

        The ONLY admission path a fresh ``publish_committed_branch`` may use.
        The caller no longer chooses an epoch: the revocation re-check, the
        policy gate, the prior-record scan, the caller's ``precondition``, the
        allocation, and the append all happen under one ``admissions.lock``, so
        two trains racing one repository can never observe the same high water.

        ``make_request(epoch, attempt_id)`` is called INSIDE the lock and both
        values it was handed are enforced on what it returned, so a caller
        cannot smuggle a different epoch or attempt identity into the record.
        """
        import fcntl

        from .live import authenticated_partition_floor

        self._authorize()
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self._require_generation()
                if self.epoch_blocked() or self.policy is None:
                    raise PermissionError("broker admission denied")
                records = self._records()

                for record in records:
                    if record.request.attempt_id != attempt_id:
                        continue
                    rebuilt = make_request(record.epoch, attempt_id)
                    if rebuilt.lease_epoch != record.epoch:
                        raise ValueError(
                            "admit_next dedup must rebuild at the prior epoch "
                            f"{record.epoch}, got {rebuilt.lease_epoch}"
                        )
                    if rebuilt.attempt_id != attempt_id:
                        raise ValueError("admit_next dedup rebuilt a different attempt_id")
                    if rebuilt != record.request:
                        raise ValueError("conflicting authority for an existing attempt_id")
                    # A dedup hit is still an ADMISSION decision, not a cache read:
                    # re-apply the CURRENT policy and the caller's in-lock
                    # precondition, so a resume cannot keep publishing under
                    # authority that has since been revoked.
                    if not self.policy(rebuilt):
                        raise PermissionError("broker admission denied")
                    if not precondition():
                        raise PermissionError("broker admission precondition denied")
                    return record

                if not precondition():
                    raise PermissionError("broker admission precondition denied")

                # The floor is the authenticated MAXIMUM of canonical history and
                # the armed receipt's legacy high water.  An absent, invalid, or
                # drifted receipt is denial — never a silent restart at epoch 1.
                epoch = max(
                    self._canonical_high_water(records),
                    authenticated_partition_floor(self.root),
                ) + 1

                request = make_request(epoch, attempt_id)
                if request.lease_epoch != epoch:
                    raise ValueError(
                        f"admit_next requires lease_epoch == allocated epoch {epoch}, "
                        f"got {request.lease_epoch}"
                    )
                if request.attempt_id != attempt_id:
                    raise ValueError("admit_next requires the supplied attempt_id")
                if not self.policy(request):
                    raise PermissionError("broker admission denied")

                record = AdmissionRecord(len(records) + 1, epoch, request)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                return record
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def admit(self, request: AdmissionRequest) -> AdmissionRecord:
        import fcntl
        self._authorize()
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # The legacy finalized path is fenced by the same in-lock
                # generation re-check as `admit_next`: a stale writer must not
                # append here just because it avoided the allocator.
                self._require_generation()
                if self.epoch_blocked() or self.policy is None or not self.policy(request):
                    raise PermissionError("broker admission denied")
                records = self._records()
                for record in records:
                    if record.request.idempotency_key == request.idempotency_key:
                        if record.request != request: raise ValueError("conflicting idempotency key")
                        return record
                if records and request.lease_epoch < max(r.epoch for r in records): raise PermissionError("stale epoch")
                record = AdmissionRecord(len(records) + 1, request.lease_epoch, request)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(record), sort_keys=True) + "\n"); stream.flush(); os.fsync(stream.fileno())
                return record
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def replay(self) -> tuple[AdmissionRecord, ...]: return tuple(self._records())
