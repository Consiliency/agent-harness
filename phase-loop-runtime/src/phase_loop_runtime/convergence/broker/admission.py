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

# ah#288: returns a denial REASON (truthy) to refuse admission, or None/"" to allow.
# Receives the durable log as it stands inside the lock, immediately before mutation.
AdmissionPrecondition = Callable[[tuple["AdmissionRecord", ...]], str | None]


class LinearizableAdmissionStore:
    """Append-only admission log guarded by an OS advisory lock."""
    def __init__(self, root: Path, policy: BrokerAdmissionPolicy | None = None, epoch_blocked: Callable[[], bool] | None = None) -> None:
        self.root, self.policy, self.epoch_blocked = root, policy, epoch_blocked or (lambda: False)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path, self.lock_path = root / "admissions.jsonl", root / "admissions.lock"

    def _records(self) -> list[AdmissionRecord]:
        if not self.path.exists(): return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line); raw["request"] = AdmissionRequest(**raw["request"]); records.append(AdmissionRecord(**raw))
        return records

    def admit(self, request: AdmissionRequest, *, precondition: AdmissionPrecondition | None = None) -> AdmissionRecord:
        import fcntl
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self.epoch_blocked() or self.policy is None or not self.policy(request):
                    raise PermissionError("broker admission denied")
                records = self._records()
                for record in records:
                    if record.request.idempotency_key == request.idempotency_key:
                        if record.request != request: raise ValueError("conflicting idempotency key")
                        return record
                # ah#288: a caller-supplied gate over the DURABLE LOG, evaluated INSIDE the
                # advisory lock and BEFORE any mutation. `policy` cannot express this: it
                # sees only the request, never the records. Checking the log outside
                # `admit` would be a TOCTOU — `admit` appends sequence 1 unconditionally,
                # so a post-admit "baseline" test is satisfied by the caller's OWN write
                # (the retry/poison-record exploit the #288 CR flushed out).
                #
                # Placed AFTER dedup on purpose: an idempotent resume of an already
                # admitted request must still return its prior record without re-proving
                # a baseline that its own admission has since changed.
                if precondition is not None:
                    denial = precondition(tuple(records))
                    if denial: raise PermissionError(denial)
                if records and request.lease_epoch < max(r.epoch for r in records): raise PermissionError("stale epoch")
                record = AdmissionRecord(len(records) + 1, request.lease_epoch, request)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(record), sort_keys=True) + "\n"); stream.flush(); os.fsync(stream.fileno())
                return record
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def admit_next(self, make_request: Callable[[int], AdmissionRequest], *, attempt_id: str,
                   precondition: AdmissionPrecondition | None = None) -> AdmissionRecord:
        """ah#288: admit at a BROKER-ALLOCATED epoch.

        `admit` takes the epoch from the caller, which makes fencing self-asserted: a
        caller picks its own number AND its own identity, so it can always present a
        combination with no prior history and walk past any "must be higher than before"
        rule. Here the epoch is `max+1` computed INSIDE the lock — the caller has no say,
        so "strictly above" holds by construction and there is no lineage to forge.

        Idempotency is keyed on `attempt_id`, which must NOT encode the epoch: a resume
        has to find its own earlier record BEFORE an epoch is allocated, or it would be
        handed a fresh number every time and never de-dup.
        """
        import fcntl
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                records = self._records()
                for record in records:
                    if record.request.attempt_id == attempt_id:
                        return record  # idempotent resume, before any allocation
                if precondition is not None:
                    denial = precondition(tuple(records))
                    if denial: raise PermissionError(denial)
                epoch = (max(r.epoch for r in records) if records else 0) + 1
                request = make_request(epoch)
                if self.epoch_blocked() or self.policy is None or not self.policy(request):
                    raise PermissionError("broker admission denied")
                record = AdmissionRecord(len(records) + 1, epoch, request)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(record), sort_keys=True) + "\n"); stream.flush(); os.fsync(stream.fileno())
                return record
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def replay(self) -> tuple[AdmissionRecord, ...]: return tuple(self._records())
