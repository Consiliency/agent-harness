"""The sole provider-agnostic mutation boundary."""
from __future__ import annotations

import functools

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    BrokerRequest,
    BrokerTerminalEvidence,
    BrokerVerb,
    DeltaReadmitAuthority,
    DeltaReadmitReceipt,
    PreAdmissionEnvelope,
    PublishCommittedBranchResult,
    publish_committed_branch_idempotency_key,
)
from phase_loop_runtime.convergence.provider_contracts import (
    PROVIDER_COMPLETION_CLASSIFICATIONS,
    ProviderCompletionClassification,
    TerminalOutcomeState,
    validate_terminal_transition,
)
from . import evidence as evidence_module
from .evidence import BrokerEvidenceStore, EvidenceRecord, PostAmbiguityObservation


class BrokerProviderAdapter(Protocol):
    def execute(self, request: BrokerRequest) -> tuple[PublishCommittedBranchResult | None, BrokerTerminalEvidence]: ...


class BrokerClient(Protocol):
    def execute(self, request: BrokerRequest) -> "BrokerExecutionResult": ...
    def readmit_advanced_head(self, auth: DeltaReadmitAuthority) -> DeltaReadmitReceipt | None: ...



@dataclass(frozen=True)
class BrokerExecutionResult:
    accepted: bool
    evidence: BrokerTerminalEvidence
    publish_result: PublishCommittedBranchResult | None = None
    reason: str = ""
    #: agent-harness#1577 (D3): whether THIS call entered the provider adapter.
    #: A replay of stored evidence, or a refusal before provider entry, is False.
    provider_call_made: bool = False
    #: agent-harness#1591: a definite provider outcome on a key whose row was
    #: already ``outcome_ambiguous_blocked``.  In memory only; its ``durable``
    #: says whether the side file holds it.  Never makes the result accepted.
    observed_after_ambiguity: PostAmbiguityObservation | None = None


#: agent-harness#1591: ``BrokerExecutionResult.reason`` for an observation.
EFFECT_OBSERVED_AFTER_AMBIGUITY = "effect_observed_after_ambiguity"
NO_EFFECT_OBSERVED_AFTER_AMBIGUITY = "no_effect_observed_after_ambiguity"


def _observed_after_ambiguity_reason(observation: PostAmbiguityObservation) -> str:
    return (
        EFFECT_OBSERVED_AFTER_AMBIGUITY
        if observation.is_effect
        else NO_EFFECT_OBSERVED_AFTER_AMBIGUITY
    )


class PublicationRecoveryRequired(PermissionError):
    """An already-admitted publish transaction for the current head has no supported recovery.

    Raised before any owner, admission or evidence write (agent-harness#1296).
    """


#: Transaction states past ``COMMITTED_HEAD_RESOLVED``: the transaction was
#: admitted in some generation.  A failed provider outcome leaves it here
#: (``TERMINAL_SEALED`` normally; earlier after an adapter exception or crash).
_ADMITTED_TRANSACTION_STATES = (
    "ADMISSION_DURABLE",
    "BROKER_INTENT_DURABLE",
    "ADAPTER_STARTED",
    "TERMINAL_SEALED",
)


@dataclass(frozen=True)
class AdapterStartOwnership:
    """Repository-visible, pre-effect ownership of one provider entry."""

    repository_identity: str
    idempotency_key: str
    transaction_id: str
    attempt_id: str
    committed_head: str
    adapter_operation: str
    owner_nonce: str
    effect_key: str
    sealed: bool = False


def _owner_path(root: Path) -> Path:
    return Path(root) / "adapter-start-owner.json"


def _owner_atomic_write(path: Path, owner: AdapterStartOwnership) -> None:
    body = json.dumps(owner.__dict__, sort_keys=True, separators=(",", ":")) + "\n"
    _owner_atomic_write_bytes(path, body.encode("utf-8"))


def _owner_atomic_write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    with temporary.open("wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _restore_owner_bytes(root: Path, prior: bytes | None) -> None:
    """Put the owner path back exactly as the section found it (agent-harness#1314).

    ``prior`` is the raw byte content read under the same ``admissions.lock``
    acquisition before the owner write, or ``None`` when no owner existed.  The
    exact bytes are restored, not a re-serialization: rotation binds the
    predecessor's sealed owner (its ``transaction_id``), and an owner written by
    another runtime version may serialize differently.
    """
    path = _owner_path(root)
    if prior is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
        _fsync_directory(path.parent)
    else:
        _owner_atomic_write_bytes(path, prior)


class AdapterStartOwnerLive(PermissionError):
    """The unsealed adapter-start owner's writer is still running (agent-harness#1313).

    Retryable contention, not ambiguity: nothing was written.  A writer holds an
    advisory ``flock`` on the owner file's inode from the owner write until its
    attempt ends; the kernel releases it when the process dies.
    """


class AdapterStartOwnerContended(PermissionError):
    """The owner section was lost to another live publisher twice in one publish.

    Retryable contention, like :class:`AdapterStartOwnerLive`: nothing was
    written and no provider call was made.
    """


class UnsealedOwnerBlocksPartition(PermissionError):
    """An unsealed adapter-start owner was promoted to ``outcome_ambiguous_blocked``.

    The partition is now blocked by that owner's effect key until a partition
    rotation adjudicates it.  ``effect_key`` and ``transaction_id`` are the
    observed owner's: the key to dispose and the transaction to bind.
    """

    def __init__(self, message: str, *, effect_key: str, transaction_id: str) -> None:
        super().__init__(message)
        self.effect_key = effect_key
        self.transaction_id = transaction_id


class PartitionEpochBlocked(PermissionError):
    """The partition's generation is permanently blocked by ambiguity.

    ``blocking_keys`` are the effect keys whose evidence in this generation is
    ``outcome_ambiguous_blocked``.  It is empty when the block is carried by the
    partition receipt (legacy archived ambiguity) rather than by a key here.
    """

    def __init__(self, message: str, *, blocking_keys: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.blocking_keys = tuple(blocking_keys)


class ProviderEntryRefused(PermissionError):
    """A refusal after this attempt's admission became durable and before provider entry.

    The attempt's unsealed owner (and its ``provider_call_in_flight`` intent,
    when recorded) stays, as agent-harness#1578 option (i) requires.  A direct
    rotation refuses an intent without a terminal; the next attempt promotes the
    owner to ``outcome_ambiguous_blocked``, which a rotation then adjudicates.
    The message is the original refusal's, which is chained as ``__cause__``.
    """

    def __init__(self, message: str, *, effect_key: str, transaction_id: str) -> None:
        super().__init__(message)
        self.effect_key = effect_key
        self.transaction_id = transaction_id


def _hold_owner_liveness(root: Path) -> int:
    """Take the live writer's lock on the just-written owner inode; return the descriptor.

    Called under ``admissions.lock`` right after the owner write, so no prober
    (which decides under the same lock) can observe the owner unlocked while its
    writer runs.  Writes are ``os.replace``: a later seal makes a new inode, and
    this descriptor on the old one is then inert.  ``O_RDWR`` because ``flock``
    over NFS is emulated with a POSIX write lock.
    """
    import fcntl

    descriptor = os.open(
        str(_owner_path(root)), os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise AdapterStartOwnerLive(
            "adapter-start owner inode is locked by another live writer; retry"
        ) from None
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _owner_writer_alive(root: Path) -> bool:
    """Probe whether the current owner's writer still holds its liveness lock.

    A fresh ``open`` is a new open file description, so a writer on another
    thread of this process reads alive too.  An absent file, or an owner whose
    writer never locked (an older runtime) or has exited, reads not alive.
    """
    import fcntl

    try:
        descriptor = os.open(
            str(_owner_path(root)), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        )
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def read_adapter_start_owner(root: Path, *, repository_identity: str) -> AdapterStartOwnership | None:
    path = _owner_path(root)
    if not path.exists():
        return None
    owner = AdapterStartOwnership(**json.loads(path.read_text(encoding="utf-8")))
    if owner.repository_identity != repository_identity:
        raise PermissionError("adapter-start ownership belongs to another repository")
    return owner


def append_adapter_start_owner(
    root: Path,
    owner: AdapterStartOwnership,
    *,
    authorize=None,
    lock_held: bool = False,
) -> AdapterStartOwnership:
    """Fsync the owner before admission.  An unsealed owner is never replaced.

    ``lock_held=True`` declares that the caller already holds the exclusive
    ``admissions.lock`` (ah#789: one critical section spanning owner and
    admission); the write then happens under the caller's acquisition.
    """
    import fcntl

    root = Path(root)

    def append() -> AdapterStartOwnership:
        if authorize is not None:
            authorize()
        current = read_adapter_start_owner(root, repository_identity=owner.repository_identity)
        if current is not None and not current.sealed:
            return current
        _owner_atomic_write(_owner_path(root), owner)
        return owner

    if lock_held:
        return append()
    if authorize is not None:
        authorize()
    else:
        root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "admissions.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return append()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def validate_adapter_start_owner(
    root: Path,
    owner: AdapterStartOwnership,
    *,
    authorize=None,
) -> AdapterStartOwnership:
    """Revalidate exact ownership and generation under the shared store lock."""
    import fcntl

    lock_path = Path(root) / "admissions.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if authorize is not None:
                authorize()
            current = read_adapter_start_owner(
                root, repository_identity=owner.repository_identity
            )
            if current != owner or current.sealed:
                raise PermissionError("adapter-start ownership changed before provider entry")
            return current
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def seal_adapter_start_owner(
    root: Path,
    owner: AdapterStartOwnership,
    *,
    authorize=None,
    lock_held: bool = False,
) -> AdapterStartOwnership:
    """Seal exact ownership under the shared store lock."""
    import fcntl

    def seal() -> AdapterStartOwnership:
        if authorize is not None:
            authorize()
        current = read_adapter_start_owner(
            root, repository_identity=owner.repository_identity
        )
        if current != owner or current.sealed:
            raise PermissionError("adapter-start ownership changed before terminal seal")
        sealed = AdapterStartOwnership(**{**current.__dict__, "sealed": True})
        _owner_atomic_write(_owner_path(root), sealed)
        return sealed

    if lock_held:
        return seal()
    lock_path = Path(root) / "admissions.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return seal()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# The frozen interface is owned by SL-2, while the append-only evidence module
# stays an SL-1-owned file.  Export the versioned record through that module so
# existing evidence readers and the crash-injection seam share one surface.
if not hasattr(evidence_module, "AdapterStartOwnership"):
    evidence_module.AdapterStartOwnership = AdapterStartOwnership
    evidence_module.read_adapter_start_owner = read_adapter_start_owner
    evidence_module.append_adapter_start_owner = append_adapter_start_owner
    evidence_module.validate_adapter_start_owner = validate_adapter_start_owner
    evidence_module.seal_adapter_start_owner = seal_adapter_start_owner


def _fabpub_active() -> bool:
    from .live import fabpub_capability_active

    return fabpub_capability_active()


def _advance_transaction(transaction, state: str) -> None:
    if transaction is not None and transaction.state != state:
        transaction.project(state)


def _unsealed_owner_refusal(owner: AdapterStartOwnership) -> UnsealedOwnerBlocksPartition:
    return UnsealedOwnerBlocksPartition(
        "unsealed adapter-start owner blocks fresh provider effect",
        effect_key=owner.effect_key,
        transaction_id=owner.transaction_id,
    )


def _provider_entry_refusal(error: PermissionError, key: str, envelope) -> ProviderEntryRefused:
    """Type a ``WriterGenerationBlocked`` in the provider-entry window (board round 1).

    The result is ``ProviderEntryGenerationRefused``: still a
    ``WriterGenerationBlocked`` for callers that catch it, with the same message.
    Only generation refusals are passed here; every other ``PermissionError``
    in the window propagates unchanged.
    """
    from .live import ProviderEntryGenerationRefused

    return ProviderEntryGenerationRefused(
        str(error), effect_key=key, transaction_id=envelope.transaction_id
    )


def _provider_effect_refusal(
    error: PermissionError, key: str, envelope, *, execute_returned: bool, result=None
):
    """Type a ``WriterGenerationBlocked`` that refused the ambiguity record after entry.

    agent-harness#1628: the result is ``ProviderEffectGenerationRefused``, still
    a ``WriterGenerationBlocked`` with the same message, and never a
    ``ProviderEntryRefused``: the provider was entered.  agent-harness#1684:
    ``execute_returned`` says whether the adapter returned (its terminal record
    was then refused) or raised; a returned result's PR URL, head and branch are
    carried, never discarded.
    """
    from .live import ProviderEffectGenerationRefused

    return ProviderEffectGenerationRefused(
        str(error),
        effect_key=key,
        transaction_id=envelope.transaction_id,
        execute_returned=execute_returned,
        pr_url=getattr(result, "pr_url", None),
        head_sha=getattr(result, "head_sha", None),
        branch=getattr(result, "branch", None),
    )


class BrokerService:
    def __init__(self, admission_store, evidence_store: BrokerEvidenceStore, adapter: BrokerProviderAdapter, contracts=PROVIDER_COMPLETION_CLASSIFICATIONS) -> None:
        self.admission_store = admission_store
        self.evidence_store = evidence_store
        self.adapter = adapter
        self.contracts = contracts

    def readmit_advanced_head(self, auth: DeltaReadmitAuthority) -> DeltaReadmitReceipt | None:
        from phase_loop_runtime.convergence.broker.live import canonical_repository_identity
        if auth.adapter_worktree:
            try:
                worktree_repo = canonical_repository_identity(auth.adapter_worktree)
                if worktree_repo != auth.repository:
                    raise PermissionError(f"repository mismatch: {worktree_repo} != {auth.repository}")
            except (PermissionError, ValueError):
                raise
            except Exception as e:
                raise PermissionError(str(e)) from e

        if self.evidence_store.epoch_blocked:
            return None

        rec = self.admission_store.admit_next(auth)
        if rec is None:
            return None

        if isinstance(rec, DeltaReadmitReceipt):
            return rec

        return DeltaReadmitReceipt(
            repository=auth.repository,
            branch=auth.branch,
            prior_head_sha=auth.prior_head_sha,
            proposed_head_sha=auth.proposed_head_sha,
            allocated_epoch=rec.epoch,
            attempt_identity=auth.attempt_identity,
            authority_digest=auth.authority_digest,
        )

    def _dedup_key(self, request: BrokerRequest) -> str:
        if request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH:
            if request.scope_correction_of:
                from phase_loop_runtime.publish_scope_correction import effect_key

                return effect_key(request.repo, request.branch, request.head_sha, request.scope_correction_of)
            base = publish_committed_branch_idempotency_key(request.repo, request.branch, request.head_sha)
        else:
            base = getattr(request.admission, "idempotency_key", None) or getattr(
                request.admission, "transaction_id", ""
            )
        return f"{request.verb.value}\0{base}"

    def _replay(self, request: BrokerRequest, key: str, current: EvidenceRecord) -> BrokerExecutionResult:
        observed = current.state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED
        result = (
            PublishCommittedBranchResult(request.branch, request.head_sha, current.evidence_reference)
            if observed and request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH
            else None
        )
        observation = (
            self._stored_post_ambiguity_observation(key)
            if current.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
            and request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH
            else None
        )
        if observation is not None:
            # agent-harness#1591: every retry gets the same observed handoff.
            return BrokerExecutionResult(
                False,
                BrokerTerminalEvidence(key, current.state.value, current.evidence_reference),
                None,
                reason=_observed_after_ambiguity_reason(observation),
                provider_call_made=False,
                observed_after_ambiguity=observation,
            )
        return BrokerExecutionResult(
            observed,
            BrokerTerminalEvidence(key, current.state.value, current.evidence_reference),
            result,
            provider_call_made=False,
        )

    def _stored_post_ambiguity_observation(self, key: str) -> PostAmbiguityObservation | None:
        """The observation bound to ``key``'s current ambiguity, read-only (agent-harness#1591).

        An effect wins over a no-effect.  An unreadable side file yields ``None``
        here (the plain ambiguity); the ceremony and the re-admission refuse it.
        """
        observations = evidence_module.read_post_ambiguity_observations(self.evidence_store.root)
        if observations is evidence_module.UNREADABLE:
            return None
        digest = evidence_module.ambiguity_digest(self.evidence_store.root, key)
        bound = [
            observation
            for observation in observations.get(key, ())
            if observation.ambiguity_digest == digest
        ]
        for observation in bound:
            if observation.is_effect:
                return observation
        return bound[-1] if bound else None

    def _legacy_terminal_replay(self, request: BrokerRequest, key: str) -> BrokerExecutionResult | None:
        """Promote only a receipt-authenticated exact historical key."""
        if request.verb is not BrokerVerb.PUBLISH_COMMITTED_BRANCH:
            return None
        for legacy_key, provenance in self.evidence_store.authenticated_legacy_records().items():
            serialized = provenance.get("serialized_repository")
            if not isinstance(serialized, str):
                raise PermissionError("legacy terminal has no preserved repository preimage")
            expected = f"publish_committed_branch\0{publish_committed_branch_idempotency_key(serialized, request.branch, request.head_sha)}"
            if legacy_key != expected:
                continue
            promoted = self.evidence_store.promote_legacy_terminal(legacy_key)
            current = self.evidence_store.replay().get(key)
            if current is None:
                self.evidence_store.record_intent(key)
                current = self.evidence_store.record_terminal(
                    EvidenceRecord(key, TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, promoted.evidence_reference)
                )
            return self._replay(request, key, current)
        return None

    def _validated_envelope(self, request: BrokerRequest):
        if not isinstance(request.admission, PreAdmissionEnvelope):
            raise TypeError("fresh publish_committed_branch requires PreAdmissionEnvelope")
        envelope = request.admission
        if not request.adapter_worktree or not Path(request.adapter_worktree).is_absolute():
            raise PermissionError("fresh publish requires an absolute adapter_worktree")
        if Path(request.adapter_worktree).resolve() != Path(envelope.adapter_worktree).resolve():
            raise PermissionError("request and envelope adapter worktrees differ")
        if request.repo != envelope.canonical_repository_identity:
            raise PermissionError("request repository does not equal envelope canonical identity")
        if request.head_sha != envelope.committed_head_sha or envelope.expected_commit_oid != envelope.committed_head_sha:
            raise PermissionError("request/envelope committed head binding differs")

        from phase_loop_runtime.publishing import (
            PublishTransactionState,
            inspect_publish_resume_candidate,
            validate_transaction_owned_workspace,
        )

        candidate = inspect_publish_resume_candidate(
            Path(request.adapter_worktree),
            checkpoint_root=Path(envelope.checkpoint_root),
            node_id=envelope.node_id,
        )
        if candidate.transaction is None and envelope.node_id != "node":
            candidate = inspect_publish_resume_candidate(
                Path(request.adapter_worktree),
                checkpoint_root=Path(envelope.checkpoint_root),
                node_id="node",
            )
        transaction = candidate.transaction
        if candidate.state not in PublishTransactionState.ORDERED[2:] or transaction is None:
            raise PermissionError("fresh publish names no exact committed transaction")
        validate_transaction_owned_workspace(Path(request.adapter_worktree), transaction)
        bindings = (
            "canonical_repository_identity", "transaction_id", "original_commit_message_sha256",
            "pre_trailer_intent_sha256", "final_commit_message_sha256", "expected_commit_oid",
            "committed_head_sha", "final_commit_object_sha256",
        )
        if any(getattr(envelope, name) != getattr(transaction, name) for name in bindings):
            raise PermissionError("envelope does not bind the durable transaction")
        if request.branch != transaction.branch or tuple(request.owned_paths) != tuple(transaction.owned_paths):
            raise PermissionError("publish request differs from the durable transaction")
        lineage = transaction._payload.get("scope_correction", {})
        if request.scope_correction_of != lineage.get("predecessor_id", ""):
            raise PermissionError("publish request differs from correction lineage")
        if request.scope_correction_of:
            from phase_loop_runtime.publish_scope_correction import validate_source

            validate_source(Path(request.adapter_worktree), transaction)
        if Path(request.adapter_worktree).resolve() != transaction.repo:
            raise PermissionError("adapter worktree does not equal transaction workspace")
        authority = transaction.envelope_authority_preimage
        for name in (
            "train_id", "node_id", "action", "roadmap_digest", "effective_code_digest",
            "dependency_digest", "verification_plan_digest", "expected_version_predicate",
            "authority_domain_scope", "operation_identity",
        ):
            if envelope.__dict__.get(name) != authority.get(name):
                raise PermissionError("envelope authority differs from the durable transaction")
        return envelope, transaction

    @staticmethod
    def _final_admission(envelope: PreAdmissionEnvelope, request: BrokerRequest, epoch: int, attempt_id: str) -> AdmissionRequest:
        approval_payload = {
            name: getattr(envelope, name)
            for name in (
                "roadmap_digest", "effective_code_digest", "dependency_digest",
                "verification_plan_digest", "operation_identity", "transaction_id",
                "pre_trailer_intent_sha256", "final_commit_object_sha256",
            )
        }
        approval_digest = hashlib.sha256(json.dumps(approval_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        from phase_loop_runtime.publish_scope_correction import effect_key

        idempotency_key = effect_key(request.repo, request.branch, request.head_sha, request.scope_correction_of)
        return AdmissionRequest(
            attempt_id,
            epoch,
            envelope.transaction_id,
            approval_digest,
            envelope.expected_version_predicate,
            envelope.authority_domain_scope,
            idempotency_key,
        )


    def _epoch_blocked_refusal(self) -> PartitionEpochBlocked:
        """``epoch permanently blocked``, naming the keys that block it (agent-harness#1573)."""
        try:
            stored = self.evidence_store.replay()
        except (OSError, PermissionError, ValueError):
            # The refusal stands; it only loses the names of the blocking keys.
            stored = {}
        blocking = tuple(
            sorted(
                key
                for key, record in stored.items()
                if record.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
            )
        )
        return PartitionEpochBlocked("epoch permanently blocked", blocking_keys=blocking)

    def _block_unsealed_owner(self, owner: AdapterStartOwnership) -> bool:
        """Resolve one observed owner under the repository evidence lock.

        Return true only when the owner remains an unknown provider effect and
        was durably promoted to permanent ambiguity. A terminal already known
        to be effect or no-effect retires the owner and permits a fresh head.
        An owner whose writer is still alive (agent-harness#1313) raises
        ``AdapterStartOwnerLive`` before any evidence append.
        """
        import fcntl

        self.evidence_store._authorize()
        with self.evidence_store.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.evidence_store._authorize()
                # ah#789 (ah#803 round-2, codex): the early probe ran OUTSIDE this
                # lock.  A newer writer can land an incompatible admission line in
                # the gap, so the store is re-validated under the lock before any
                # evidence append — the refusal stays typed and mutation-free.
                self.admission_store._records()
                current_owner = evidence_module.read_adapter_start_owner(
                    self.evidence_store.root,
                    repository_identity=owner.repository_identity,
                )
                if current_owner is None or current_owner.sealed:
                    return False
                current = self.evidence_store.replay().get(current_owner.effect_key)
                if current is not None and current.state in (
                    TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                    TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
                ):
                    evidence_module.seal_adapter_start_owner(
                        self.evidence_store.root,
                        current_owner,
                        authorize=self.evidence_store._authorize,
                        lock_held=True,
                    )
                    return False
                if (
                    current is None
                    or current.state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT
                ) and _owner_writer_alive(self.evidence_store.root):
                    # agent-harness#1313: the writer is mid-attempt.  Promoting now
                    # would turn a live publish into permanent ambiguity; refuse
                    # retryable and write nothing.
                    raise AdapterStartOwnerLive(
                        f"adapter-start owner for effect key {current_owner.effect_key!r} "
                        f"(transaction {current_owner.transaction_id}) is held by a live "
                        "writer mid-attempt; retry after it finishes. No evidence was written."
                    )
                if current is None:
                    current = self.evidence_store._append_locked(
                        EvidenceRecord(
                            current_owner.effect_key,
                            TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT,
                        )
                    )
                if current.state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT:
                    self.evidence_store._append_locked(
                        EvidenceRecord(
                            current_owner.effect_key,
                            TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED,
                            "unsealed-adapter-start-owner",
                        )
                    )
                return True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _record_terminal_and_seal_owner(
        self,
        owner: AdapterStartOwnership,
        record: EvidenceRecord,
        *,
        branch: str = "",
    ) -> tuple[EvidenceRecord, PostAmbiguityObservation | None]:
        """Linearize a known terminal and owner retirement under one lock.

        agent-harness#1591: when the key's row is already
        ``outcome_ambiguous_blocked`` and ``record`` is a definite outcome
        (effect or no-effect), nothing is appended to the evidence log and the
        owner is not sealed.  The outcome is returned as an observation and,
        when the on-disk owner is still exactly ``owner`` (nonce included) and
        unsealed, appended to the side file under this same acquisition.
        Returns ``(stored_row, observation_or_None)``.
        """
        import fcntl

        # agent-harness#1633: a DRAINING latch alone does not refuse here.  A
        # rotation holds admissions.lock across its drain, so this writer waits on
        # the lock while its held lease keeps the ceremony from draining; a revoked
        # or stale lease and a superseded generation root still refuse.  The
        # ordinary terminal append and owner seal re-authorize strictly below.
        self.evidence_store._authorize(allow_draining=True)
        with self.evidence_store.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.evidence_store._authorize(allow_draining=True)
                current = self.evidence_store.replay().get(record.idempotency_key)
                if current is None:
                    raise ValueError("intent must precede evidence")
                if current.state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED and record.state in (
                    TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                    TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
                ):
                    return current, self._post_ambiguity_observation_locked(owner, record, branch)
                self.evidence_store._authorize()
                if current == record:
                    terminal = current
                else:
                    if not validate_terminal_transition(current.state, record.state):
                        raise ValueError("invalid terminal transition")
                    terminal = self.evidence_store._append_locked(record)
                if terminal.state in (
                    TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                    TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
                ):
                    evidence_module.seal_adapter_start_owner(
                        self.evidence_store.root,
                        owner,
                        authorize=self.evidence_store._authorize,
                        lock_held=True,
                    )
                return terminal, None
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _post_ambiguity_observation_locked(
        self,
        owner: AdapterStartOwnership,
        record: EvidenceRecord,
        branch: str,
    ) -> PostAmbiguityObservation:
        """Bind ``record`` to the blocked row and this attempt's owner; append if still ours.

        Caller holds ``admissions.lock`` and has run ``_authorize()``.  Never
        raises for a lost binding: a different or sealed owner, or a side file
        that cannot take a row, returns the observation with ``durable=False``.
        """
        root = self.evidence_store.root
        observation = PostAmbiguityObservation(
            idempotency_key=record.idempotency_key,
            observed_state=record.state.value,
            evidence_reference=record.evidence_reference,
            head_sha=owner.committed_head,
            branch=branch,
            transaction_id=owner.transaction_id,
            owner_nonce=owner.owner_nonce,
            ambiguity_digest=evidence_module.ambiguity_digest(root, record.idempotency_key) or "",
        )
        current_owner = evidence_module.read_adapter_start_owner(
            root, repository_identity=owner.repository_identity
        )
        if current_owner != owner or current_owner.sealed or not observation.ambiguity_digest:
            return observation
        durable = evidence_module.append_post_ambiguity_observation(
            root,
            observation,
            authorize=functools.partial(self.evidence_store._authorize, allow_draining=True),
            lock_held=True,
        )
        return PostAmbiguityObservation(**observation.row(), durable=durable)

    def _owner_and_admission_under_one_lock(
        self,
        request: BrokerRequest,
        owner: AdapterStartOwnership,
        make_request,
        attempt_id: str,
        *,
        recovery_key: str | None = None,
        liveness_holder: list[int] | None = None,
        prior_owner_holder: list[bytes | None] | None = None,
    ) -> tuple[AdapterStartOwnership | None, AdapterStartOwnership | None, object]:
        """ah#789: durable owner and admission under ONE ``admissions.lock`` acquisition.

        Inside the section, in order: (1) the admission store must be readable
        by THIS runtime (typed refusal before any write); (2) the owner is
        re-read under the lock — an unsealed foreign owner is returned to the
        caller, who resolves it OUTSIDE the section through
        ``_block_unsealed_owner`` (which takes the same lock itself); (3) the
        transaction must be admissible; (4) the owner is written; (5) the
        admission is allocated.  No writer of any runtime version can
        interleave between (4) and (5).

        (3) runs BEFORE the owner write (agent-harness#1296): a denied
        precondition used to leave a fresh unsealed owner behind, which the
        next attempt promoted to permanent ambiguity.  A fresh publish needs
        ``COMMITTED_HEAD_RESOLVED``.  A recovery (``recovery_key`` set) leaves
        the checkpoint where it is, so its state cannot gate a second
        admission; instead the generation's evidence must hold no record for
        the key.  A concurrent retry that passed ``execute``'s replay check
        before the first attempt's terminal therefore refuses here and makes
        no second provider call.

        Any refusal after (4) restores the owner path to the exact bytes it held
        on entry, under this same acquisition (agent-harness#1314): the owner
        never reached the provider, so no effect is possible, and a leftover
        unsealed owner would otherwise become permanent ambiguity.  A simulated
        crash (``PublishCrashInjected``) gets no cleanup, as a real one would not.

        Right after (4) the writer takes an advisory lock on the owner inode
        (agent-harness#1313) and appends its descriptor to ``liveness_holder``;
        the caller closes it when the attempt ends.  Without a holder the lock
        is released when the section returns.

        ``prior_owner_holder`` receives the owner bytes the section found
        (agent-harness#1578): ``_restore_unadmitted_owner`` puts them back if the
        ``ADMISSION_DURABLE`` projection fails right after the section.

        Returns ``(foreign_owner, recorded_owner, admission_record)``; exactly
        one of ``foreign_owner`` / ``recorded_owner`` is set.
        """
        import fcntl

        self.evidence_store._authorize()
        with self.admission_store.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.admission_store._records()
                current_owner = evidence_module.read_adapter_start_owner(
                    self.evidence_store.root,
                    repository_identity=request.repo,
                )
                if current_owner is not None and not current_owner.sealed:
                    return current_owner, None, None
                state = self._validated_envelope(request)[1].state
                if recovery_key is None and state != "COMMITTED_HEAD_RESOLVED":
                    raise PermissionError(
                        f"broker admission precondition denied: publish transaction is {state}, "
                        "admission requires COMMITTED_HEAD_RESOLVED; no owner or admission was written"
                    )
                if recovery_key is not None:
                    if state not in _ADMITTED_TRANSACTION_STATES:
                        raise PermissionError(
                            f"broker admission precondition denied: recovered transaction is {state}"
                        )
                    if self.evidence_store.replay().get(recovery_key) is not None:
                        raise PermissionError(
                            "broker admission precondition denied: the re-admitting generation "
                            "already re-admitted the transaction; retry to replay its evidence"
                        )
                owner_path = _owner_path(self.evidence_store.root)
                # Absent, or a sealed owner: an unsealed one returned above.
                prior_owner_bytes = owner_path.read_bytes() if owner_path.exists() else None
                if prior_owner_holder is not None:
                    prior_owner_holder.append(prior_owner_bytes)
                # Indirection through evidence_module keeps the durable write a crash seam.
                # A sealed owner is a completed prior effect, not a lock on a new head.
                recorded_owner = evidence_module.append_adapter_start_owner(
                    self.evidence_store.root,
                    owner,
                    authorize=self.evidence_store._authorize,
                    lock_held=True,
                )
                held: list[int] = liveness_holder if liveness_holder is not None else []
                try:
                    if recorded_owner == owner:
                        held.append(_hold_owner_liveness(self.evidence_store.root))
                    admission_record = self.admission_store.admit_next(
                        make_request,
                        attempt_id=attempt_id,
                        # Already decided above under this same lock acquisition.
                        precondition=lambda: True,
                        lock_held=True,
                    )
                except Exception as error:
                    from phase_loop_runtime.publishing import PublishCrashInjected

                    # Never retire an owner this attempt did not write.
                    if not isinstance(error, PublishCrashInjected) and recorded_owner == owner:
                        try:
                            _restore_owner_bytes(self.evidence_store.root, prior_owner_bytes)
                        except OSError:
                            # The owner stays unsealed: today's fail-closed shape.
                            pass
                    raise
                finally:
                    if liveness_holder is None:
                        for descriptor in held:
                            os.close(descriptor)
                return None, recorded_owner, admission_record
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _provider_entry_guard(
        self, key: str, recorded_owner: AdapterStartOwnership
    ) -> EvidenceRecord | None:
        """Authorize provider entry, or return the stored row that forbids it (agent-harness#1577).

        Within ONE ``admissions.lock`` acquisition (the lock every runtime
        version's ``_block_unsealed_owner`` takes): the on-disk owner must equal
        ``recorded_owner`` exactly, nonce included, and be unsealed, AND the key's
        evidence row must be ``provider_call_in_flight``.  ``EvidenceRecord`` has
        no attempt field; owner equality under this lock is what proves the
        in-flight row is still this attempt's.  Returns ``None`` when the
        provider may be called.  Otherwise returns the stored row and writes
        nothing: a promotion by an older prober (window (b)) is reported as the
        ambiguity the store holds, not as a ``PermissionError``.  A failed
        generation check still raises, as ``validate_adapter_start_owner`` did.
        """
        import fcntl

        self.evidence_store._authorize()
        with self.evidence_store.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.evidence_store._authorize()
                current_owner = evidence_module.read_adapter_start_owner(
                    self.evidence_store.root,
                    repository_identity=recorded_owner.repository_identity,
                )
                stored = self.evidence_store.replay().get(key)
                if stored is None:
                    # record_intent ran in this generation; no row means the store
                    # is not the one this attempt wrote.  Fail closed, typed.
                    raise ProviderEntryRefused(
                        f"effect key {key!r} has no evidence row before provider entry; "
                        "no provider call was made and nothing was written",
                        effect_key=key,
                        transaction_id=recorded_owner.transaction_id,
                    )
                if (
                    current_owner == recorded_owner
                    and not current_owner.sealed
                    and stored.state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT
                ):
                    return None
                return stored
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _restore_unadmitted_owner(
        self,
        key: str,
        recorded_owner: AdapterStartOwnership,
        transaction,
        prior_owner_bytes: bytes | None,
    ) -> None:
        """Undo this attempt's owner after a failed ``ADMISSION_DURABLE`` projection (agent-harness#1578).

        Option (i) only, and only while the checkpoint is still
        ``COMMITTED_HEAD_RESOLVED``: once it is admitted, a restored owner makes
        the retry refuse in ``_recovery_authority`` with no rotation able to help,
        while a left owner is promoted and a truthful ``attested_not_landed``
        rotation recovers it.  Under a fresh ``admissions.lock`` acquisition the
        generation must still be this attempt's (a superseded writer must not
        touch that generation's files), the on-disk owner must be exactly
        ``recorded_owner``, and the key must have no evidence row.  Anything else
        leaves the state as it is; the admission line left behind is harmless
        (``admit_next`` dedups the retry by ``attempt_id``).  Never raises.
        """
        import fcntl

        try:
            with self.evidence_store.lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    durable = json.loads(transaction.checkpoint_path.read_text(encoding="utf-8"))
                    if durable.get("state") != "COMMITTED_HEAD_RESOLVED":
                        return
                    # ``_authorize`` revalidates the evidence store's generation
                    # (``evidence._require_generation``) in-lock.
                    self.evidence_store._authorize()
                    require_admission_generation = getattr(
                        self.admission_store, "_require_generation", None
                    )
                    if require_admission_generation is not None:
                        require_admission_generation()
                    current_owner = evidence_module.read_adapter_start_owner(
                        self.evidence_store.root,
                        repository_identity=recorded_owner.repository_identity,
                    )
                    if current_owner != recorded_owner or current_owner.sealed:
                        return
                    if self.evidence_store.replay().get(key) is not None:
                        return
                    _restore_owner_bytes(self.evidence_store.root, prior_owner_bytes)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except Exception:
            # Fail closed: the owner stays, and the next attempt promotes it.
            return

    def _recovery_authority(self, request: BrokerRequest, key: str, envelope, transaction) -> dict:
        """Authorize re-admitting an already-admitted transaction, or refuse typed.

        agent-harness#1296: the only supported recovery is a partition rotation
        whose attestation disposes this exact effect key ``attested_not_landed``
        and binds this exact transaction (the predecessor owner's
        ``transaction_id``).  agent-harness#1310: that rotation may be earlier
        than the active generation, provided no generation since holds evidence
        for the key (``attested_not_landed_recovery`` walks the authenticated
        chain).  agent-harness#1591: the disposition authorizes nothing when the
        generation it adjudicated recorded a post-ambiguity effect for the key, or
        its side file is unreadable; that escalates to the maintainer.  Nothing is
        written here.
        """
        from .live import (
            RecoveryChainSuperseded,
            attested_not_landed_recovery,
            generation_store_root,
            post_ambiguity_effect_refusal,
        )

        tid = envelope.transaction_id

        def refuse(why: str, next_step: str) -> PublicationRecoveryRequired:
            return PublicationRecoveryRequired(
                f"publish transaction {tid} is {transaction.state} for the current head "
                f"{request.head_sha} (effect key {key!r}), but {why}. Fresh admission requires "
                "COMMITTED_HEAD_RESOLVED; an already-admitted transaction is re-admitted only "
                "under an authenticated attested_not_landed rotation that binds it. "
                f"Next step: {next_step}. No owner, admission or provider call was made."
            )

        try:
            recovery = attested_not_landed_recovery(self.evidence_store.root, key)
        except RecoveryChainSuperseded as error:
            raise refuse(
                f"the attested_not_landed disposition for it no longer authorizes a re-admission: {error}",
                f"inspect generation {error.generation}'s broker evidence for the key with the "
                "maintainer; a disposition authorizes one re-admission, and a rotation can dispose "
                "the key again only while it is blocked in the active generation",
            ) from error
        except (RuntimeError, PermissionError, OSError, ValueError) as error:
            # LegacyCutoverConflict is a RuntimeError; routing/compatibility
            # refusals are PermissionErrors.  All of them are the same answer.
            raise refuse(
                f"the rotation chain does not authenticate ({type(error).__name__}: {error})",
                "restore the rotation's receipt, journal and sealed inventory bytes; do not "
                "rotate again over a generation that does not authenticate",
            ) from error
        if recovery is None:
            # ``execute`` replays any record the active generation holds for the
            # key, so reaching here means it holds none: the key is not blocked
            # in the active generation and no rotation can dispose it now.
            raise refuse(
                "no rotation in the partition's authenticated receipt chain disposes it "
                "attested_not_landed as its latest adjudication, and the active generation holds "
                "no evidence for the key",
                "a rotation cannot help here, because an attestation only disposes keys that are "
                "blocked in the active generation; inspect the publish checkpoint and the broker "
                "evidence with the maintainer",
            )
        observed = post_ambiguity_effect_refusal(
            generation_store_root(self.evidence_store.root, recovery["predecessor_generation"]), key
        )
        if observed is not None:
            # agent-harness#1591 (D2): a ceremony without the side-file refusal (an
            # older runtime) disposed an effect the provider reported as landed.
            raise refuse(
                f"rotation {recovery['cutover_id']!r} disposes the key attested_not_landed, but "
                f"generation {recovery['predecessor_generation']} recorded {observed}",
                "escalate to the maintainer; do not re-publish. The provider reported this "
                "effect after the key was blocked, so a re-admission could publish it twice",
            )
        if recovery["transaction_id"] is None:
            raise refuse(
                f"rotation {recovery['cutover_id']!r} disposes the key attested_not_landed but binds no "
                "transaction id (its predecessor had no adapter-start owner for the key)",
                "escalate to the maintainer; the disposition cannot be bound to this transaction "
                "and must not be inferred",
            )
        if recovery["transaction_id"] != tid:
            raise refuse(
                f"rotation {recovery['cutover_id']!r} adjudicated transaction "
                f"{recovery['transaction_id']}, not this one",
                f"retry with the publication context of transaction {recovery['transaction_id']}",
            )
        # The provider request is built from THIS call's base/draft/pr_body; the
        # attestation adjudicated the transaction as frozen, so they must be its own.
        frozen = {"base": request.base, "draft": request.draft, "pr_body": request.pr_body}
        differing = sorted(
            name for name, value in frozen.items() if getattr(transaction, name, None) != value
        )
        if differing:
            raise refuse(
                f"this request's {', '.join(differing)} differ from the transaction's frozen values; "
                "a recovery re-publishes exactly what was admitted",
                f"retry with the transaction's own {', '.join(differing)}",
            )
        return {
            **recovery,
            "recovered_transaction_state": transaction.state,
            "expected_commit_oid": transaction.expected_commit_oid,
            "committed_head_sha": transaction.committed_head_sha,
            "final_commit_object_sha256": transaction.final_commit_object_sha256,
            "exact_ref": transaction.exact_ref,
            "branch": transaction.branch,
            "owned_paths": list(transaction.owned_paths),
            "canonical_repository_identity": transaction.canonical_repository_identity,
            "roadmap_digest": envelope.roadmap_digest,
            "effective_code_digest": envelope.effective_code_digest,
            "dependency_digest": envelope.dependency_digest,
            "verification_plan_digest": envelope.verification_plan_digest,
            "operation_identity": envelope.operation_identity,
            "base": transaction.base,
            "draft": transaction.draft,
            "pr_body_sha256": hashlib.sha256(transaction.pr_body.encode("utf-8")).hexdigest(),
        }

    def _fresh_publish(self, request: BrokerRequest, key: str) -> BrokerExecutionResult:
        envelope, transaction = self._validated_envelope(request)
        # ah#789 early probe: a runtime that cannot read the admission store or
        # the evidence journal refuses HERE, typed, before any owner path runs
        # (``_block_unsealed_owner`` appends evidence; it must never be reached
        # by an incompatible reader).  Both reads create nothing.
        self.admission_store.probe_readable()
        self.evidence_store.replay()
        existing_owner = evidence_module.read_adapter_start_owner(
            self.evidence_store.root,
            repository_identity=request.repo,
        )
        if existing_owner is not None and not existing_owner.sealed:
            if self._block_unsealed_owner(existing_owner):
                raise _unsealed_owner_refusal(existing_owner)
        if self.evidence_store.epoch_blocked:
            raise self._epoch_blocked_refusal()
        # agent-harness#1296: a transaction already admitted in some generation
        # (a failed outcome leaves it there) is re-admitted only under an
        # authenticated attested_not_landed rotation, and refused typed before
        # any write otherwise.  This runs AFTER the unsealed-owner resolution
        # above, so a crashed attempt still becomes the durable ambiguity a
        # rotation adjudicates.  The broker never moves the checkpoint; the SDK
        # closeout seals it after the terminal, and the recovery record keeps the
        # state it was recovered from.
        recovery = (
            self._recovery_authority(request, key, envelope, transaction)
            if transaction.state in _ADMITTED_TRANSACTION_STATES
            else None
        )

        def advance(state: str) -> None:
            if recovery is None:
                _advance_transaction(transaction, state)

        attempt_id = hashlib.sha256(
            b"FABPUB-PUBLISH-ATTEMPT-v1\0"
            + f"{request.repo}\0{request.branch}\0{request.head_sha}".encode()
            + (b"\0scope-correction-v1" if request.scope_correction_of else b"")
        ).hexdigest()
        owner = AdapterStartOwnership(
            request.repo,
            key,
            envelope.transaction_id,
            attempt_id,
            request.head_sha,
            request.verb.value,
            hashlib.sha256(os.urandom(32)).hexdigest()[:32],
            key,
        )
        def make_request(epoch: int, supplied_attempt_id: str) -> AdmissionRequest:
            return self._final_admission(envelope, request, epoch, supplied_attempt_id)

        if recovery is not None:
            # Provenance first: a failed write leaves no owner behind.
            transaction.record_recovery(recovery)

        # agent-harness#1313: the descriptor locking this attempt's owner inode
        # is held until the attempt ends (after the terminal seal), on every
        # path, including exceptions; process death releases it too.
        liveness: list[int] = []
        prior_owner: list[bytes | None] = []
        try:
            # One critical section for owner + admission.  An unsealed foreign owner
            # observed INSIDE the section is resolved outside it exactly as before
            # (``_block_unsealed_owner``), then the section is entered once more; a
            # second foreign owner is a live contender and refuses fail-closed.
            for _entry in (1, 2):
                foreign_owner, recorded_owner, admission_record = (
                    self._owner_and_admission_under_one_lock(
                        request,
                        owner,
                        make_request,
                        attempt_id,
                        recovery_key=key if recovery is not None else None,
                        liveness_holder=liveness,
                        prior_owner_holder=prior_owner,
                    )
                )
                if foreign_owner is None:
                    break
                if self._block_unsealed_owner(foreign_owner):
                    raise _unsealed_owner_refusal(foreign_owner)
            else:
                # A retired owner was replaced by another live publisher between the
                # two entries: a retryable contention loss, not permanent ambiguity.
                raise AdapterStartOwnerContended(
                    "unsealed adapter-start owner contended twice in one publish; retry"
                )
            try:
                advance("ADMISSION_DURABLE")
            except Exception as error:
                from phase_loop_runtime.publishing import PublishCrashInjected

                if not isinstance(error, PublishCrashInjected) and prior_owner:
                    self._restore_unadmitted_owner(
                        key, recorded_owner, transaction, prior_owner[-1]
                    )
                raise
            # agent-harness#1578 (option i): every later failure up to the provider
            # call (``record_intent``, the checkpoint projections, the guard's own
            # authorization, a refused service-generation lease) leaves the owner
            # and the admitted checkpoint as they are.  The next attempt promotes the
            # owner, and an ``attested_not_landed`` rotation recovers it.  Only a
            # ``WriterGenerationBlocked`` in this window is re-raised, as
            # ``ProviderEntryGenerationRefused`` (still a ``WriterGenerationBlocked``;
            # same message, cause chained), and the guard raises its own
            # ``ProviderEntryRefused``, so the caller can say "retry once, then
            # rotate" (agent-harness#1594 ask 1).  Every other ``PermissionError``
            # (an errno-bearing ``OSError``, ``*StoreIncompatible``) propagates
            # unchanged.
            from .live import WriterGenerationBlocked

            try:
                self.evidence_store.record_intent(key)
                advance("BROKER_INTENT_DURABLE")
                from phase_loop_runtime.publishing import _crash_at

                _crash_at("after_broker_intent_before_adapter_started")
                stored = self._provider_entry_guard(key, recorded_owner)
            except WriterGenerationBlocked as error:
                raise _provider_entry_refusal(error, key, envelope) from error
            if stored is not None:
                # agent-harness#1577: the key is no longer this attempt's in-flight
                # record (an older prober promoted the owner after the section).
                # Nothing is written, the owner stays unsealed, and the checkpoint
                # stays ``BROKER_INTENT_DURABLE``: the provider was never entered.
                return BrokerExecutionResult(
                    False,
                    BrokerTerminalEvidence(key, stored.state.value, stored.evidence_reference),
                    reason="outcome_ambiguous",
                    provider_call_made=False,
                )
            advance("ADAPTER_STARTED")
            allocated_epoch = getattr(admission_record, "epoch", None)
            if allocated_epoch is None:
                allocated_epoch = admission_record.lease_epoch
            finalized = make_request(allocated_epoch, attempt_id)
            adapter_request = BrokerRequest(
                request.verb, finalized, request.repo, request.branch, request.head_sha,
                request.owned_paths, base=request.base, draft=request.draft, pr_body=request.pr_body,
                adapter_worktree=request.adapter_worktree,
                scope_correction_of=request.scope_correction_of,
            )
            # agent-harness#1574 (SG-F1): set immediately before the adapter call.  A
            # failure before it (the service-generation lease, which a DRAINING
            # latch refuses) never reached the provider and is not ambiguity.
            provider_entered = False
            # agent-harness#1684: set once ``adapter.execute`` returns, so a
            # refused terminal record is not reported as an adapter failure.
            provider_returned = False
            result = None
            observation: PostAmbiguityObservation | None = None
            try:
                acquire_lease = getattr(self.adapter, "_acquire_service_generation_lease", None)
                temporary_lease = (
                    acquire_lease(self.evidence_store.root) if acquire_lease is not None else None
                )
                try:
                    provider_entered = True
                    result, evidence = self.adapter.execute(adapter_request)
                    provider_returned = True
                    _crash_at("after_provider_return_before_terminal")
                    state = TerminalOutcomeState(evidence.terminal_state)
                    reference = result.pr_url if result is not None else evidence.evidence_reference
                    # agent-harness#1591 (D3), agent-harness#1633: recorded while this
                    # writer still holds its generation lease.  A rotation that started
                    # during the call holds admissions.lock across its drain: the write
                    # waits on that lock, the held lease makes the ceremony refuse
                    # "predecessor writers did not drain" (it is retried), and only a
                    # writer with no held lease, or a cleared one, loses the observation.
                    terminal, observation = self._record_terminal_and_seal_owner(
                        recorded_owner, EvidenceRecord(key, state, reference), branch=request.branch
                    )
                    if observation is not None and observation.durable:
                        _crash_at("after_post_ambiguity_observation")
                finally:
                    release_lease = getattr(self.adapter, "_release_service_generation_lease", None)
                    if release_lease is not None:
                        release_lease(temporary_lease)
                if observation is not None:
                    return self._observed_after_ambiguity_result(key, terminal, observation)
                advance("TERMINAL_SEALED")
                return BrokerExecutionResult(state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, BrokerTerminalEvidence(key, terminal.state.value, terminal.evidence_reference), result, provider_call_made=True)
            except Exception as error:
                from phase_loop_runtime.publishing import PublishCrashInjected

                if isinstance(error, PublishCrashInjected):
                    raise
                if not provider_entered:
                    # Nothing to record: the owner and the in-flight row stay as on
                    # any other pre-provider failure (agent-harness#1578, option i).
                    if isinstance(error, WriterGenerationBlocked):
                        raise _provider_entry_refusal(error, key, envelope) from error
                    raise
                if observation is not None:
                    # The observation was handled before a later step (the lease
                    # release) failed; report it, not a fresh ambiguity.
                    stored = self.evidence_store.replay().get(key) or EvidenceRecord(
                        key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
                    )
                    return self._observed_after_ambiguity_result(key, stored, observation)
                # The broker returns the state the store holds and never invents one.
                current = self.evidence_store.replay().get(key)
                if current is not None and current.state in (
                    TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                    TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
                ):
                    # The terminal is durable and only a later step failed (the
                    # owner seal, the TERMINAL_SEALED projection).  An unsealed owner
                    # with a known terminal is sealed by the next fresh publish's
                    # ``_block_unsealed_owner``; a retry replays the terminal.
                    replayed = self._replay(request, key, current)
                    return BrokerExecutionResult(
                        replayed.accepted,
                        replayed.evidence,
                        result if replayed.accepted and result is not None else replayed.publish_result,
                        provider_call_made=True,
                    )
                # agent-harness#1628: both writes are generation-fenced.  A
                # ``WriterGenerationBlocked`` here (a DRAINING latch, a revoked
                # shared lease) is re-raised as ``ProviderEffectGenerationRefused``
                # with no terminal written: the row stays ``provider_call_in_flight``
                # and the owner unsealed, so the caller can say "retry once" (the
                # retry's ``_block_unsealed_owner`` promotes it).  It records
                # whether the adapter returned (its terminal record was refused)
                # and carries the returned result (agent-harness#1684).  Every
                # other error from these writes propagates unchanged.
                try:
                    if current is None:
                        self.evidence_store.record_intent(key)
                        current = self.evidence_store.replay().get(key)
                    if current is not None and current.state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT:
                        current = self.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "adapter-exception"))
                except WriterGenerationBlocked as refused:
                    raise _provider_effect_refusal(
                        refused, key, envelope, execute_returned=provider_returned, result=result
                    ) from refused
                if current is None:
                    # Unreachable after record_intent; never fabricate a row.
                    raise RuntimeError(
                        f"effect key {key!r} has no evidence row after provider entry"
                    ) from error
                return BrokerExecutionResult(False, BrokerTerminalEvidence(key, current.state.value, current.evidence_reference), reason="outcome_ambiguous", provider_call_made=True)
        finally:
            for descriptor in liveness:
                os.close(descriptor)

    @staticmethod
    def _observed_after_ambiguity_result(
        key: str, stored: EvidenceRecord, observation: PostAmbiguityObservation
    ) -> BrokerExecutionResult:
        """agent-harness#1591: the store stays ambiguous; the outcome is reported, never accepted."""
        return BrokerExecutionResult(
            False,
            BrokerTerminalEvidence(key, stored.state.value, stored.evidence_reference),
            None,
            reason=_observed_after_ambiguity_reason(observation),
            provider_call_made=True,
            observed_after_ambiguity=observation,
        )

    def execute(self, request: BrokerRequest) -> BrokerExecutionResult:
        if request.scope_correction_of:
            from phase_loop_runtime.publish_scope_correction import authorize

            if not _fabpub_active():
                raise PermissionError("scope correction requires active FABPUB")
            authorize(self, request)
        key = self._dedup_key(request)
        current = self.evidence_store.replay().get(key)
        if current and current.state is not TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT:
            return self._replay(request, key, current)
        legacy = self._legacy_terminal_replay(request, key)
        if legacy is not None:
            return legacy
        if (
            _fabpub_active()
            and request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH
            and not isinstance(request.admission, PreAdmissionEnvelope)
            and self.evidence_store.epoch_blocked
        ):
            raise self._epoch_blocked_refusal()
        if _fabpub_active() and request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH:
            return self._fresh_publish(request, key)
        if _fabpub_active() and isinstance(request.admission, PreAdmissionEnvelope):
            raise TypeError("PreAdmissionEnvelope is valid only for publish_committed_branch")
        contract = next((contract for contract in self.contracts if contract.verb == request.verb.value and contract.provider == "github"), None)
        if contract is None or contract.classification is not ProviderCompletionClassification.SUPPORTED:
            try:
                evidence = self.evidence_store.rejected_before_start(key, "provider-classification")
            except PermissionError as error:
                if not (_fabpub_active() and "no authenticated partition receipt" in str(error)):
                    raise
                evidence = EvidenceRecord(key, TerminalOutcomeState.REJECTED_BEFORE_START, "provider-classification")
            return BrokerExecutionResult(False, BrokerTerminalEvidence(key, evidence.state.value, evidence.evidence_reference), reason="provider_not_supported")
        if self.evidence_store.epoch_blocked:
            raise self._epoch_blocked_refusal()
        try:
            self.admission_store.admit(request.admission)
            self.evidence_store.record_intent(key)
        except PermissionError as error:
            # The finalized non-publish surface remains a test/legacy adapter
            # compatibility seam.  Activated production routing supplies a
            # receipt-bound store; an isolated direct service has no namespace
            # authority to persist, but may still exercise its non-publish
            # provider contract without weakening fresh publish gating.
            if not (
                _fabpub_active()
                and request.verb is not BrokerVerb.PUBLISH_COMMITTED_BRANCH
                and "no armed LegacyRepositoryPartitionReceipt" in str(error)
            ):
                raise
            result, evidence = self.adapter.execute(request)
            state = TerminalOutcomeState(evidence.terminal_state)
            return BrokerExecutionResult(
                state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                BrokerTerminalEvidence(key, state.value, evidence.evidence_reference),
                result,
                provider_call_made=True,
            )
        try:
            result, evidence = self.adapter.execute(request)
            state = TerminalOutcomeState(evidence.terminal_state)
            reference = result.pr_url if result is not None else evidence.evidence_reference
            recorded = self.evidence_store.record_terminal(EvidenceRecord(key, state, reference))
            return BrokerExecutionResult(state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, BrokerTerminalEvidence(key, recorded.state.value, recorded.evidence_reference), result, provider_call_made=True)
        except Exception:
            recorded = self.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "adapter-exception"))
            return BrokerExecutionResult(False, BrokerTerminalEvidence(key, recorded.state.value, recorded.evidence_reference), reason="outcome_ambiguous", provider_call_made=True)
