"""Append-only terminal evidence for broker operations."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState, validate_terminal_transition


@dataclass(frozen=True)
class EvidenceRecord:
    idempotency_key: str
    state: TerminalOutcomeState
    evidence_reference: str = ""


def _fabpub_active() -> bool:
    from .live import fabpub_capability_active

    return fabpub_capability_active()


#: "The caller declared no lease at all", distinct from an explicit
#: ``generation_lease=None``.  A DECLARED absence is denied under an ACTIVE
#: generation; an undeclared one is validated against latch state only.
_UNDECLARED = object()


def _require_generation(root: Path, generation_lease) -> None:
    from .live import require_current_generation

    if generation_lease is _UNDECLARED:
        require_current_generation(root, None, strict=False)
    else:
        require_current_generation(root, generation_lease, strict=True)


class BrokerEvidenceStore:
    def __init__(self, root: Path, generation_lease=_UNDECLARED) -> None:
        self.root = root
        # SL1-SOL-02: the FABPUB WriterGenerationLease.v1 this store writes
        # under, revalidated by exact nonce inside the store lock before every
        # append.  SL1-SOL-07: while FABPUB is active the canonical tree is NOT
        # created at construction; `_authorize` proves receipt + generation first.
        self.generation_lease = generation_lease
        if not _fabpub_active():
            root.mkdir(parents=True, exist_ok=True)
        self.path = root / "evidence.jsonl"
        # ah#288/#199: the SAME lock file LinearizableAdmissionStore uses (both stores are
        # constructed on one `root`). A revocation (outcome_ambiguous_blocked) written here
        # must not be able to land between an admission's epoch_blocked check and its
        # append. The admission store re-checks epoch_blocked INSIDE this lock (see
        # build_* wiring), so sharing one boundary makes "is the epoch blocked?" and
        # "block the epoch" mutually exclusive. Deadlock-safe: no evidence write happens
        # while the admission lock is held (execute admits, THEN records).
        self.lock_path = root / "admissions.lock"
    def replay(self) -> dict[str, EvidenceRecord]:
        result: dict[str, EvidenceRecord] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                raw = json.loads(line); raw["state"] = TerminalOutcomeState(raw["state"]); result[raw["idempotency_key"]] = EvidenceRecord(**raw)
        return result
    def _authorize(self) -> None:
        """Authenticate BEFORE any directory creation, then create the tree."""
        from .live import load_partition_receipt

        _require_generation(self.root, self.generation_lease)
        if _fabpub_active() and load_partition_receipt(self.root) is None:
            raise PermissionError(
                f"legacy_cutover_conflict: no authenticated partition receipt governs "
                f"{self.root}; refusing to create or append canonical evidence"
            )
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def epoch_blocked(self) -> bool:
        if any(r.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED for r in self.replay().values()):
            return True
        # FABPUB: permanent ambiguity survives the legacy cutover.  A retired
        # legacy store whose archived history held an outcome_ambiguous_blocked
        # record — or an orphaned provider_call_in_flight, whose effect is
        # unknown — permanently blocks EXACTLY its authenticated repository
        # partition, carried forward by that partition's receipt.  Absent a
        # receipt this is a no-op, so pre-FABPUB stores behave exactly as before.
        return self._legacy_partition_blocked()

    def _legacy_partition_blocked(self) -> bool:
        try:
            from .live import partition_is_ambiguity_blocked
        except Exception:  # pragma: no cover - defensive import guard
            return False
        return partition_is_ambiguity_blocked(self.root)

    def authenticated_legacy_records(self) -> dict[str, dict]:
        """Exact legacy effect key -> full provenance, or ``{}`` when unattested."""
        from .live import load_partition_receipt, sealed_partition_effects

        receipt = load_partition_receipt(self.root)
        if receipt is None:
            return {}
        return sealed_partition_effects(receipt)

    def _mint_legacy_promotion(self, key: str):
        """Module-internal: the ONLY route to a promotion capability."""
        from .live import _mint_cutover_promotion_capability

        return _mint_cutover_promotion_capability(self.root, key)

    def promote_legacy_terminal(self, key: str) -> EvidenceRecord:
        """Promote ONE authenticated legacy terminal into the canonical store.

        SL1-SOL-10: the capability is minted HERE, under the write lock, from
        the authenticated receipt and the CURRENT archive bytes — a caller
        cannot pass one in, and a stale capability cannot be replayed.  Intent,
        terminal, and provenance are appended under one lock hold, provenance
        first, so a crash can never leave a promoted terminal unattributed.
        """
        import fcntl

        self._authorize()
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                capability = self._mint_legacy_promotion(key)
                provenance = capability.provenance
                reference = provenance["evidence_reference"]
                current = self.replay().get(key)
                if current is not None and current.state is (
                    TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED
                ):
                    if current.evidence_reference != reference:
                        raise PermissionError(
                            f"canonical terminal for {key!r} references "
                            f"{current.evidence_reference!r} but the authenticated legacy "
                            f"terminal references {reference!r}"
                        )
                    self._require_provenance_locked(key, provenance)
                    return current
                self._append_provenance_locked(key, provenance)
                if current is None:
                    self._append_locked(
                        EvidenceRecord(key, TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT)
                    )
                return self._append_locked(
                    EvidenceRecord(
                        key, TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, reference
                    )
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _require_provenance_locked(self, key: str, provenance: dict) -> None:
        """A promoted terminal MUST carry matching provenance; absence is denial."""
        path = self.root / "legacy-promotions.jsonl"
        recorded = None
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                if raw.get("idempotency_key") == key:
                    recorded = raw.get("promotion_provenance")
        if recorded is None:
            raise PermissionError(
                f"canonical terminal for {key!r} has no recorded promotion provenance; "
                "an unattributed terminal may not be treated as an authenticated replay"
            )
        if recorded != provenance:
            raise PermissionError(
                f"a prior promotion of {key!r} recorded different provenance; an existing "
                "terminal may not be re-attributed"
            )

    def _append_provenance_locked(self, key: str, provenance: dict) -> None:
        """Record which cutover/partition/source authorised a promotion."""
        path = self.root / "legacy-promotions.jsonl"
        body = json.dumps(
            {"idempotency_key": key, "promotion_provenance": provenance},
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        if path.exists() and body in path.read_text(encoding="utf-8"):
            return
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    def record_intent(self, key: str) -> EvidenceRecord:
        current = self.replay().get(key)
        if current: return current
        return self._append(EvidenceRecord(key, TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT))
    def record_terminal(self, record: EvidenceRecord, *, pre_linearization_proven: bool = False) -> EvidenceRecord:
        current = self.replay().get(record.idempotency_key)
        if current is None: raise ValueError("intent must precede evidence")
        if current == record: return current
        if not validate_terminal_transition(current.state, record.state, pre_linearization_proven=pre_linearization_proven): raise ValueError("invalid terminal transition")
        return self._append(record)
    def rejected_before_start(self, key: str, evidence_reference: str) -> EvidenceRecord:
        return self._append(EvidenceRecord(key, TerminalOutcomeState.REJECTED_BEFORE_START, evidence_reference))
    def _append(self, record: EvidenceRecord) -> EvidenceRecord:
        import fcntl
        self._authorize()
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # Evidence appends are fenced by the same in-lock generation
                # re-check as admissions: a writer whose generation was revoked
                # mid-flight must not record intent or a terminal.
                _require_generation(self.root, self.generation_lease)
                return self._append_locked(record)
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def _append_locked(self, record: EvidenceRecord) -> EvidenceRecord:
        # Storage-layer permanence: no write may transition OUT of a terminal
        # outcome_ambiguous_blocked record.  This is self-enforcing regardless of
        # caller path (record_terminal, rejected_before_start, record_intent), so a
        # buggy caller cannot escape the block by writing a fresh terminal record.
        current = self.replay().get(record.idempotency_key)
        if current is not None and current.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED and record != current:
            raise ValueError("outcome_ambiguous_blocked is permanent; no transition out")
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), sort_keys=True) + "\n"); stream.flush(); os.fsync(stream.fileno())
        return record
