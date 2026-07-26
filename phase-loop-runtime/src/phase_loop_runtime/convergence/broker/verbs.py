"""The sole provider-agnostic mutation boundary."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from phase_loop_runtime.convergence.contracts import BrokerRequest, BrokerTerminalEvidence, BrokerVerb, PublishCommittedBranchResult
from phase_loop_runtime.convergence.fencing import FencedAdmissionFactory
from phase_loop_runtime.convergence.provider_contracts import PROVIDER_COMPLETION_CLASSIFICATIONS, ProviderCompletionClassification, TerminalOutcomeState
from .evidence import BrokerEvidenceStore, EvidenceRecord


class BrokerProviderAdapter(Protocol):
    def execute(self, request: BrokerRequest) -> tuple[PublishCommittedBranchResult | None, BrokerTerminalEvidence]: ...
class BrokerClient(Protocol):
    def execute(self, request: BrokerRequest) -> "BrokerExecutionResult": ...
    def readmit_advanced_head(
        self, *, repo: str, branch: str, train_id: str, node_id: str, prior_head_sha: str,
        new_head_sha: str, approval, expected_version_predicate: str,
        authority_domain_scope: str,
    ) -> "ReadmitResult": ...

@dataclass(frozen=True)
class BrokerExecutionResult:
    accepted: bool
    evidence: BrokerTerminalEvidence
    publish_result: PublishCommittedBranchResult | None = None
    reason: str = ""

@dataclass(frozen=True)
class ReadmitResult:
    """ah#288: the typed outcome of a decoupled admit (admit WITHOUT publish).

    Never a bare bool — the seam verifies field-by-field, and `reason` distinguishes a
    refusal (fail-closed, expected) from an exception (fail-closed, exceptional).
    """
    accepted: bool
    granted_epoch: int
    idempotency_key: str
    reason: str = ""

def publish_committed_branch_idempotency_key(repo: str, branch: str, head_sha: str) -> str:
    return hashlib.sha256(f"{repo}\0{branch}\0{head_sha}".encode()).hexdigest()

def readmit_attempt_id(node_id: str, new_head_sha: str) -> str:
    """Deterministic attempt id for a re-admission, so a resume of the SAME advance
    de-dups instead of admitting twice.

    Deliberately does NOT encode the epoch: the broker allocates that inside the lock, so
    a resume must be able to find its own earlier record BEFORE an epoch exists.

    NUL-delimited and domain-tagged: the fields are variable-length, so plain
    concatenation would let `(node="a", sha="bc")` and `(node="ab", sha="c")` collide.
    """
    return hashlib.sha256(f"fab-readmit\0{node_id}\0{new_head_sha}".encode()).hexdigest()

class BrokerService:
    def __init__(self, admission_store, evidence_store: BrokerEvidenceStore, adapter: BrokerProviderAdapter, contracts=PROVIDER_COMPLETION_CLASSIFICATIONS) -> None:
        self.admission_store, self.evidence_store, self.adapter, self.contracts = admission_store, evidence_store, adapter, contracts
    def _dedup_key(self, request: BrokerRequest) -> str:
        # publish_committed_branch de-dups on the canonical (repo, branch, head_sha)
        # triple so a repeat under a fresh admission key is a no-op that returns the
        # SAME prior result.  Other verbs remain keyed by the admission key.
        # Every key is namespaced by verb so a cross-verb key collision can never
        # replay one verb's terminal record for a different verb (defense-in-depth).
        if request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH:
            base = publish_committed_branch_idempotency_key(request.repo, request.branch, request.head_sha)
        else:
            base = request.admission.idempotency_key
        return f"{request.verb.value}\0{base}"

    def _replay(self, request: BrokerRequest, key: str, current: EvidenceRecord) -> BrokerExecutionResult:
        observed = current.state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED
        # Idempotent recovery: a replay of a COMPLETED publish_committed_branch must
        # return the prior PublishCommittedBranchResult (pr_url persisted in the
        # evidence reference), NOT None — otherwise the caller reports it blocked.
        result = (
            PublishCommittedBranchResult(request.branch, request.head_sha, current.evidence_reference)
            if observed and request.verb is BrokerVerb.PUBLISH_COMMITTED_BRANCH
            else None
        )
        return BrokerExecutionResult(observed, BrokerTerminalEvidence(key, current.state.value, current.evidence_reference), result)

    def readmit_advanced_head(
        self, *, repo: str, branch: str, train_id: str, node_id: str, prior_head_sha: str,
        new_head_sha: str, approval, expected_version_predicate: str,
        authority_domain_scope: str,
    ) -> ReadmitResult:
        """ah#288: re-admit an ADVANCED head without publishing (the advance is already
        pushed). Deliberately does NOT touch the provider adapter.

        The epoch is ALLOCATED BY THE BROKER, not supplied by the caller. Three CR rounds
        established why: with a caller-chosen epoch AND a caller-declared node identity,
        "must be higher than this node's last" is self-asserted — a caller presents an
        unused identity, has no history, and passes. Removing both levers deletes that
        whole class, and with it the node-lineage bookkeeping earlier rounds added.

        Fail-closed on every branch. `PermissionError`/`ValueError` PROPAGATE; the seam
        maps them to `None` and recovers the admitted prefix.
        """
        if self.evidence_store.epoch_blocked:
            return ReadmitResult(False, 0, "", "revoked")

        # BASELINE: require a COMPLETED publish for this exact (repo, branch, prior_head).
        # Evidence terminal states are permanent and append-only, so this cannot become
        # false before the admit below.
        publish_key = f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0{publish_committed_branch_idempotency_key(repo, branch, prior_head_sha)}"
        prior = self.evidence_store.replay().get(publish_key)
        if prior is None or prior.state is not TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED:
            return ReadmitResult(False, 0, "", "no_prior_publish")

        factory = FencedAdmissionFactory()
        attempt_id = readmit_attempt_id(node_id, new_head_sha)

        def _make_request(epoch: int):
            lease = factory.lease(train_id=train_id, node_id=node_id, action="readmit",
                                  lease_epoch=epoch, attempt_id=attempt_id)
            return factory.create(
                lease=lease, approval=approval,
                expected_version_predicate=expected_version_predicate,
                authority_domain_scope=authority_domain_scope,
            )

        def _precondition(records) -> str | None:
            # Runs inside the store lock, before any append. An admission from THIS
            # authority must already exist: an empty log (loss/truncation/partial restore)
            # or a log holding only some other tenant's records is not a baseline.
            # Exact-or-delimited, never a bare prefix — "train-1" must not match "train-10".
            def _ours(scope: str) -> bool:
                return scope == authority_domain_scope or scope.startswith(f"{authority_domain_scope}\0")
            if not any(_ours(r.request.authority_domain_scope) for r in records):
                return "no_admission_baseline"
            return None

        record = self.admission_store.admit_next(
            _make_request, attempt_id=attempt_id, precondition=_precondition,
        )

        # ANTI-VACUITY re-read: verify the DURABLE record, not the return value.
        durable = next(
            (r for r in self.admission_store.replay() if r.request.attempt_id == attempt_id),
            None,
        )
        if durable is None or durable.epoch != record.epoch:
            return ReadmitResult(False, record.epoch, "", "admission_not_durable")
        return ReadmitResult(True, record.epoch, record.request.idempotency_key)

    def execute(self, request: BrokerRequest) -> BrokerExecutionResult:
        key = self._dedup_key(request)
        current = self.evidence_store.replay().get(key)
        if current and current.state is not TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT:
            return self._replay(request, key, current)
        contract = next((c for c in self.contracts if c.verb == request.verb.value and c.provider == "github"), None)
        if contract is None or contract.classification is not ProviderCompletionClassification.SUPPORTED:
            evidence = self.evidence_store.rejected_before_start(key, "provider-classification")
            return BrokerExecutionResult(False, BrokerTerminalEvidence(key, evidence.state.value, evidence.evidence_reference), reason="provider_not_supported")
        if self.evidence_store.epoch_blocked: raise PermissionError("epoch permanently blocked")
        self.admission_store.admit(request.admission); self.evidence_store.record_intent(key)
        try:
            result, evidence = self.adapter.execute(request)
            state = TerminalOutcomeState(evidence.terminal_state)
            # Persist the real pr_url as the evidence reference so a later replay can
            # reconstruct the identical PublishCommittedBranchResult.
            reference = result.pr_url if result is not None else evidence.evidence_reference
            recorded = self.evidence_store.record_terminal(EvidenceRecord(key, state, reference))
            return BrokerExecutionResult(state is TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, BrokerTerminalEvidence(key, recorded.state.value, recorded.evidence_reference), result)
        except Exception:
            recorded = self.evidence_store.record_terminal(EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "adapter-exception"))
            return BrokerExecutionResult(False, BrokerTerminalEvidence(key, recorded.state.value, recorded.evidence_reference), reason="outcome_ambiguous")
