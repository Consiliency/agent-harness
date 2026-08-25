"""Behavior-neutral coordination contracts shared by future runtime and broker phases."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from enum import Enum
from typing import Tuple


class BrokerVerb(str, Enum):
    PUBLISH = "publish"
    MERGE = "merge"
    RELEASE = "release"
    PACKAGE = "package"
    PUBLISH_COMMITTED_BRANCH = "publish_committed_branch"


def publish_committed_branch_idempotency_key(repo: str, branch: str, head_sha: str) -> str:
    """Return the base-free, epoch-free completed-effect key."""
    return hashlib.sha256(f"{repo}\0{branch}\0{head_sha}".encode()).hexdigest()


@dataclass(frozen=True)
class AdmissionRequest:
    """The sole fencing shape shared by RUNTIME and BROKER."""

    attempt_id: str
    lease_epoch: int
    fence_token: str
    approval_digest: str
    expected_version_predicate: str
    authority_domain_scope: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not all((self.attempt_id, self.fence_token, self.approval_digest, self.expected_version_predicate, self.authority_domain_scope, self.idempotency_key)):
            raise ValueError("admission requests require every fencing field")


@dataclass(frozen=True)
class PreAdmissionEnvelope:
    """The epoch-free authority a FRESH ``publish_committed_branch`` must carry.

    FABPUB removes the caller's ability to stamp its own fencing identity: the
    broker allocates the epoch through
    ``LinearizableAdmissionStore.admit_next`` and derives the attempt/approval
    bindings itself.  This envelope therefore carries only inputs that exist
    BEFORE allocation — repository/transaction identity and the exact commit
    bindings resolved at ``COMMITTED_HEAD_RESOLVED`` — and deliberately has no
    ``lease_epoch``, ``attempt_id``, ``fence_token``, ``approval_digest``, or
    ``idempotency_key`` field.  A caller that still wants to supply those uses
    the finalized :class:`AdmissionRequest`, which remains legal only for
    non-publish verbs and already-completed terminal replay.

    ``adapter_worktree`` is the validated execution LOCATION.  It is never the
    repository identity: ``canonical_repository_identity`` is, and the two are
    compared separately by the activated production route.
    """

    # --- envelope authority pre-image (canonicalized by the caller, re-derived
    # --- and compared by production; never an opaque caller-supplied digest).
    train_id: str
    node_id: str
    action: str
    roadmap_digest: str
    effective_code_digest: str
    dependency_digest: str
    verification_plan_digest: str
    expected_version_predicate: str
    authority_domain_scope: str
    operation_identity: str
    # --- repository + acyclic transaction identity
    canonical_repository_identity: str
    original_commit_message_sha256: str
    pre_trailer_intent_sha256: str
    transaction_id: str
    # --- separately compared post-object bindings
    final_commit_message_sha256: str
    expected_commit_oid: str
    committed_head_sha: str
    final_commit_object_sha256: str
    # --- execution location + train-local transaction root
    adapter_worktree: str
    checkpoint_root: str

    #: Fencing fields an envelope may NEVER carry; the broker derives them.
    FORBIDDEN_FIELDS = (
        "lease_epoch",
        "attempt_id",
        "fence_token",
        "approval_digest",
        "idempotency_key",
    )

    @property
    def idempotency_key(self) -> str:
        """Expose the broker-derived effect key without accepting it as input."""
        prefix = "publish:"
        if not self.operation_identity.startswith(prefix):
            raise AttributeError("idempotency_key")
        branch = self.operation_identity[len(prefix):]
        return (
            f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0"
            f"{publish_committed_branch_idempotency_key(self.canonical_repository_identity, branch, self.committed_head_sha)}"
        )

    def __post_init__(self) -> None:
        missing = [
            name
            for name in (
                "train_id", "node_id", "action", "roadmap_digest",
                "effective_code_digest", "dependency_digest",
                "verification_plan_digest", "expected_version_predicate",
                "authority_domain_scope", "operation_identity",
                "canonical_repository_identity", "original_commit_message_sha256",
                "pre_trailer_intent_sha256", "transaction_id",
                "final_commit_message_sha256", "expected_commit_oid",
                "committed_head_sha", "final_commit_object_sha256",
                "adapter_worktree", "checkpoint_root",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(f"pre-admission envelopes require every authority field: {missing}")


@dataclass(frozen=True)
class BrokerRequest:
    """A future broker request bound to one shared admission request."""

    verb: BrokerVerb
    # FABPUB widens this to a union: a FRESH publish_committed_branch carries the
    # epoch-free PreAdmissionEnvelope and is allocated through `admit_next`; a
    # finalized AdmissionRequest stays legal for non-publish verbs and for an
    # already-completed terminal replay.  SL-2 owns the dispatch/enforcement.
    admission: "AdmissionRequest | PreAdmissionEnvelope"
    repo: str
    branch: str
    head_sha: str
    owned_paths: Tuple[str, ...]
    # Base ref the broker independently re-diffs head_sha against to verify that the
    # admitted owned_paths cover the branch's actual mutation (agent-harness#202). The
    # broker uses `origin/<base>...head_sha` (three-dot), matching the #201 coordinator.
    base: str = "main"
    draft: bool = True
    pr_body: str = ""
    # The absolute worktree the adapter runs git/gh against.  It is a validated
    # EXECUTION LOCATION only: it is excluded from repository/transaction/effect
    # keys and must resolve back to `repo` (CanonicalRepositoryIdentity.v1)
    # before any effect.  `None` stays accepted only while FABPUB is inactive.
    adapter_worktree: str | None = None


@dataclass(frozen=True)
class BrokerTerminalEvidence:
    """Effect or no-effect evidence keyed by the admission idempotency key."""

    idempotency_key: str
    terminal_state: str
    evidence_reference: str


@dataclass(frozen=True)
class PublishCommittedBranchResult:
    """Frozen result shape for publish_committed_branch."""

    branch: str
    head_sha: str
    pr_url: str


class AuthoritySource(str, Enum):
    ROADMAP = "roadmap_intent"
    EVENT_LOG = "event_log_active_operation"
    GIT_HEAD = "git_commit_or_pr_head_implementation"
    MERGED_SHA = "merged_sha_merged_state"
    REGISTRY_MANIFEST = "registry_or_manifest_released_state"
    RECOVERY_EVIDENCE = "transcripts_or_phase_loop_recovery_evidence"


class InvalidationTrigger(str, Enum):
    EFFECTIVE_CODE_CHANGED = "effective_code_changed"
    ROADMAP_CHANGED = "roadmap_changed"
    BASE_SHA_CHANGED = "base_sha_changed"
    DEPENDENCY_SHA_CHANGED = "dependency_sha_changed"
    VERIFICATION_PLAN_DIGEST_CHANGED = "verification_plan_digest_changed"


@dataclass(frozen=True)
class ReconciliationBinding:
    """Versioned authority decision and the invalidations that require recomputation."""

    authority: AuthoritySource
    authority_version: str
    invalidation_model_version: str
    invalidation_triggers: Tuple[InvalidationTrigger, ...] = ()


@dataclass(frozen=True)
class ResourceIsolationDecision:
    """Fail-closed decision explaining whether two future units may run concurrently."""

    parallel_safe: bool
    reason: str


def evaluate_resource_isolation(
    *,
    left_repo: str,
    right_repo: str,
    left_owned_paths: Tuple[str, ...],
    right_owned_paths: Tuple[str, ...],
    frozen_shared_interfaces: bool,
    same_repo_mutation: bool = False,
    topological_merge: bool = False,
    release_publication: bool = False,
    evidence_known: bool = True,
) -> ResourceIsolationDecision:
    """Apply the FREEZE fail-closed concurrency predicate without scheduling work."""
    if not evidence_known:
        return ResourceIsolationDecision(False, "unknown evidence")
    if same_repo_mutation or left_repo == right_repo:
        return ResourceIsolationDecision(False, "same-repo mutation serializes")
    if topological_merge:
        return ResourceIsolationDecision(False, "topological merges serialize")
    if release_publication:
        return ResourceIsolationDecision(False, "release publication serializes")
    if not frozen_shared_interfaces:
        return ResourceIsolationDecision(False, "shared interfaces are not frozen")
    if not left_owned_paths or not right_owned_paths:
        return ResourceIsolationDecision(False, "owned-path evidence is incomplete")
    if set(left_owned_paths) & set(right_owned_paths):
        return ResourceIsolationDecision(False, "owned paths overlap")
    return ResourceIsolationDecision(True, "disjoint paths with frozen interfaces")


@dataclass(frozen=True)
class DeltaReadmitAuthority:
    """IF-0-FABREADMIT-1 immutable delta readmission request."""

    repository: str
    adapter_worktree: str
    checkpoint_root: str
    branch: str
    base: str
    prior_head_sha: str
    proposed_head_sha: str
    train_id: str
    node_id: str
    fab_run_id: str
    roadmap_digest: str
    provenance_digest: str
    owned_scope: Tuple[str, ...]

    FORBIDDEN_FIELDS = (
        "epoch",
        "attempt_id",
        "fence_token",
        "approval_digest",
        "idempotency_key",
    )

    def __post_init__(self) -> None:
        if isinstance(self.owned_scope, (list, set)):
            object.__setattr__(self, "owned_scope", tuple(self.owned_scope))
        if not self.repository or not self.branch or not self.prior_head_sha or not self.proposed_head_sha or not self.train_id or not self.node_id or not self.fab_run_id:
            raise ValueError("DeltaReadmitAuthority authority fields cannot be empty")

    @property
    def authority_digest(self) -> str:
        payload = (
            f"{self.repository}\0{self.branch}\0{self.prior_head_sha}\0"
            f"{self.proposed_head_sha}\0{self.train_id}\0{self.node_id}\0"
            f"{self.fab_run_id}\0{self.roadmap_digest}\0{self.provenance_digest}\0"
            f"{','.join(self.owned_scope)}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def attempt_identity(self) -> str:
        return hashlib.sha256(
            b"FABREADMIT-READMISSION-ATTEMPT-v1\0"
            + bytes.fromhex(self.authority_digest)
        ).hexdigest()

@dataclass(frozen=True)
class DeltaReadmitReceipt:
    """IF-0-FABREADMIT-1 readmission grant receipt."""

    repository: str
    branch: str
    prior_head_sha: str
    proposed_head_sha: str
    allocated_epoch: int
    attempt_identity: str
    authority_digest: str

    @property
    def epoch(self) -> int:
        return self.allocated_epoch


@dataclass(frozen=True)
class ReadmitAdmissionBinding:
    """ReadmitAdmissionBinding.v1 binding stored on readmit admission records."""

    prior_head_sha: str
    proposed_head_sha: str
    node_id: str
    owned_scope: Tuple[str, ...]
    authority_digest: str
    attempt_identity: str | None = field(default=None, compare=False)
