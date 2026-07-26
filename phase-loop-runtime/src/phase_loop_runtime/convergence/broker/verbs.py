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
        new_head_sha: str, next_epoch: int, approval, expected_version_predicate: str,
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

def readmit_attempt_id(node_id: str, new_head_sha: str, next_epoch: int) -> str:
    """Deterministic attempt id for a re-admission, so a resume of the SAME advance
    reproduces the SAME idempotency key and de-dups instead of admitting twice.

    NUL-delimited and domain-tagged: the fields are variable-length, so plain
    concatenation would let `(node="a", sha="bc")` and `(node="ab", sha="c")` collide.
    """
    return hashlib.sha256(f"fab-readmit\0{node_id}\0{new_head_sha}\0{next_epoch}".encode()).hexdigest()

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
        new_head_sha: str, next_epoch: int, approval, expected_version_predicate: str,
        authority_domain_scope: str,
    ) -> ReadmitResult:
        """ah#288: re-admit an ADVANCED head without publishing (the advance is already
        pushed). Deliberately does NOT touch the provider adapter.

        Fail-closed on every branch. `PermissionError`/`ValueError` from the store
        PROPAGATE — the seam caller maps them to a `None` result and recovers the
        admitted prefix; swallowing them here would report a refusal as a clean outcome.
        """
        if self.evidence_store.epoch_blocked:
            return ReadmitResult(False, next_epoch, "", "revoked")

        # BASELINE (#288 CR A1): require a COMPLETED publish for this exact
        # (repo, branch, prior_head) — not merely "some earlier record". Read from the
        # evidence store, whose terminal states are permanent and append-only, so this
        # cannot become false between here and the admit below.
        publish_key = f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0{publish_committed_branch_idempotency_key(repo, branch, prior_head_sha)}"
        prior = self.evidence_store.replay().get(publish_key)
        if prior is None or prior.state is not TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED:
            return ReadmitResult(False, next_epoch, "", "no_prior_publish")

        factory = FencedAdmissionFactory()
        lease = factory.lease(
            train_id=train_id, node_id=node_id, action="readmit", lease_epoch=next_epoch,
            attempt_id=readmit_attempt_id(node_id, new_head_sha, next_epoch),
        )
        request = factory.create(
            lease=lease, approval=approval,
            expected_version_predicate=expected_version_predicate,
            authority_domain_scope=authority_domain_scope,
        )

        def _precondition(records) -> str | None:
            # Evaluated INSIDE the store's lock, before any append.
            #   (a) empty log ⇒ no baseline can exist. `admit` would otherwise skip epoch
            #       fencing entirely via its `if records and ...` short-circuit.
            #   (b) STRICTLY ABOVE (#288 CR A2): the store itself rejects only
            #       `lease_epoch < max`, so a DIFFERENT request at the CURRENT epoch is
            #       admissible — which contradicts this verb's contract.
            #
            #       Enforced HERE and not in `LinearizableAdmissionStore` on purpose:
            #       every publish admits at `lease_epoch=1` (train_runner `action="publish"`),
            #       so an N-node train holds N distinct admissions at epoch 1. Tightening
            #       the shared store to reject `<= max` would fail every node after the
            #       first. Readmit is the only verb that requires a monotonic bump.
            if not records: return "no_admission_baseline"
            if next_epoch <= max(r.epoch for r in records): return "epoch_not_advanced"
            return None

        record = self.admission_store.admit(request, precondition=_precondition)

        # ANTI-VACUITY re-read: verify the DURABLE record, not the return value — a store
        # that accepted without persisting must not read as accepted.
        durable = next(
            (r for r in self.admission_store.replay()
             if r.request.idempotency_key == request.idempotency_key),
            None,
        )
        if durable is None or durable.epoch != next_epoch or durable.sequence != record.sequence:
            return ReadmitResult(False, next_epoch, "", "admission_not_durable")
        return ReadmitResult(True, next_epoch, request.idempotency_key)

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
