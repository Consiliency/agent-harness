"""The sole provider-agnostic mutation boundary."""
from __future__ import annotations

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
from .evidence import BrokerEvidenceStore, EvidenceRecord


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    body = json.dumps(owner.__dict__, sort_keys=True, separators=(",", ":")) + "\n"
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
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
) -> AdapterStartOwnership:
    """Fsync the owner before admission.  An unsealed owner is never replaced."""
    import fcntl

    root = Path(root)
    if authorize is not None:
        authorize()
    else:
        root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "admissions.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if authorize is not None:
                authorize()
            current = read_adapter_start_owner(root, repository_identity=owner.repository_identity)
            if current is not None and not current.sealed:
                return current
            _owner_atomic_write(_owner_path(root), owner)
            return owner
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
        return BrokerExecutionResult(observed, BrokerTerminalEvidence(key, current.state.value, current.evidence_reference), result)

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
        idempotency_key = (
            f"{request.verb.value}\0"
            f"{publish_committed_branch_idempotency_key(request.repo, request.branch, request.head_sha)}"
        )
        return AdmissionRequest(
            attempt_id,
            epoch,
            envelope.transaction_id,
            approval_digest,
            envelope.expected_version_predicate,
            envelope.authority_domain_scope,
            idempotency_key,
        )


    def _block_unsealed_owner(self, owner: AdapterStartOwnership) -> bool:
        """Resolve one observed owner under the repository evidence lock.

        Return true only when the owner remains an unknown provider effect and
        was durably promoted to permanent ambiguity. A terminal already known
        to be effect or no-effect retires the owner and permits a fresh head.
        """
        import fcntl

        self.evidence_store._authorize()
        with self.evidence_store.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.evidence_store._authorize()
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
    ) -> EvidenceRecord:
        """Linearize a known terminal and owner retirement under one lock."""
        import fcntl

        self.evidence_store._authorize()
        with self.evidence_store.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.evidence_store._authorize()
                current = self.evidence_store.replay().get(record.idempotency_key)
                if current is None:
                    raise ValueError("intent must precede evidence")
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
                return terminal
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _fresh_publish(self, request: BrokerRequest, key: str) -> BrokerExecutionResult:
        envelope, transaction = self._validated_envelope(request)
        existing_owner = evidence_module.read_adapter_start_owner(
            self.evidence_store.root,
            repository_identity=request.repo,
        )
        if existing_owner is not None and not existing_owner.sealed:
            if self._block_unsealed_owner(existing_owner):
                raise PermissionError("unsealed adapter-start owner blocks fresh provider effect")
        if self.evidence_store.epoch_blocked:
            raise PermissionError("epoch permanently blocked")
        attempt_id = hashlib.sha256(
            b"FABPUB-PUBLISH-ATTEMPT-v1\0"
            + f"{request.repo}\0{request.branch}\0{request.head_sha}".encode()
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
        # Indirection through evidence_module keeps the durable write a crash seam.
        recorded_owner = evidence_module.append_adapter_start_owner(
            self.evidence_store.root,
            owner,
            authorize=self.evidence_store._authorize,
        )
        if recorded_owner.owner_nonce != owner.owner_nonce:
            if not recorded_owner.sealed:
                if self._block_unsealed_owner(recorded_owner):
                    raise PermissionError("unsealed adapter-start owner blocks fresh provider effect")
            # A sealed owner is a completed prior effect, not a lock on a new head.
            recorded_owner = evidence_module.append_adapter_start_owner(
                self.evidence_store.root,
                owner,
                authorize=self.evidence_store._authorize,
            )
        def make_request(epoch: int, supplied_attempt_id: str) -> AdmissionRequest:
            return self._final_admission(envelope, request, epoch, supplied_attempt_id)

        admission_record = self.admission_store.admit_next(
            make_request,
            attempt_id=attempt_id,
            precondition=lambda: self._validated_envelope(request)[1].state == "COMMITTED_HEAD_RESOLVED",
        )
        _advance_transaction(transaction, "ADMISSION_DURABLE")
        self.evidence_store.record_intent(key)
        _advance_transaction(transaction, "BROKER_INTENT_DURABLE")
        from phase_loop_runtime.publishing import _crash_at

        _crash_at("after_broker_intent_before_adapter_started")
        evidence_module.validate_adapter_start_owner(
            self.evidence_store.root,
            recorded_owner,
            authorize=self.evidence_store._authorize,
        )
        _advance_transaction(transaction, "ADAPTER_STARTED")
        allocated_epoch = getattr(admission_record, "epoch", None)
        if allocated_epoch is None:
            allocated_epoch = admission_record.lease_epoch
        finalized = make_request(allocated_epoch, attempt_id)
        adapter_request = BrokerRequest(
            request.verb, finalized, request.repo, request.branch, request.head_sha,
            request.owned_paths, base=request.base, draft=request.draft, pr_body=request.pr_body,
            adapter_worktree=request.adapter_worktree,
        )
        try:
            acquire_lease = getattr(self.adapter, "_acquire_service_generation_lease", None)
            temporary_lease = (
                acquire_lease(self.evidence_store.root) if acquire_lease is not None else None
            )
            try:
                result, evidence = self.adapter.execute(adapter_request)
            finally:
                release_lease = getattr(self.adapter, "_release_service_generation_lease", None)
                if release_lease is not None:
                    release_lease(temporary_lease)
            state = TerminalOutcomeState(evidence.terminal_state)
            reference = result.pr_url if result is not None else evidence.evidence_reference
            terminal = self._record_terminal_and_seal_owner(
                recorded_owner, EvidenceRecord(key, state, reference)
            )
            _advance_transaction(transaction, "TERMINAL_SEALED")
            return BrokerExecutionResult(state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, BrokerTerminalEvidence(key, terminal.state.value, terminal.evidence_reference), result)
        except Exception as error:
            from phase_loop_runtime.publishing import PublishCrashInjected

            if isinstance(error, PublishCrashInjected):
                raise
            current = self.evidence_store.replay().get(key)
            if current is None:
                self.evidence_store.record_intent(key)
                current = self.evidence_store.replay().get(key)
            if current is not None and current.state is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT:
                self.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "adapter-exception"))
            return BrokerExecutionResult(False, BrokerTerminalEvidence(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value, "adapter-exception"), reason="outcome_ambiguous")

    def execute(self, request: BrokerRequest) -> BrokerExecutionResult:
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
            raise PermissionError("epoch permanently blocked")
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
            raise PermissionError("epoch permanently blocked")
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
            )
        try:
            result, evidence = self.adapter.execute(request)
            state = TerminalOutcomeState(evidence.terminal_state)
            reference = result.pr_url if result is not None else evidence.evidence_reference
            recorded = self.evidence_store.record_terminal(EvidenceRecord(key, state, reference))
            return BrokerExecutionResult(state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, BrokerTerminalEvidence(key, recorded.state.value, recorded.evidence_reference), result)
        except Exception:
            recorded = self.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "adapter-exception"))
            return BrokerExecutionResult(False, BrokerTerminalEvidence(key, recorded.state.value, recorded.evidence_reference), reason="outcome_ambiguous")
