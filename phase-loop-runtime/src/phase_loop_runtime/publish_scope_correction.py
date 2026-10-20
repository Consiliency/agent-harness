"""PublishScopeCorrection.v1: one successor to an exact local scope refusal.

The original canonical effect and commit are immutable. This explicit operation
has a separate, single successor key; ordinary publication replay is unchanged.
"""
from __future__ import annotations

import base64
import fcntl
from dataclasses import asdict
from pathlib import Path

from .convergence.contracts import BrokerVerb, publish_committed_branch_idempotency_key
from .convergence.provider_contracts import TerminalOutcomeState

MODE = "scope-correction-v1"


class ScopeCorrectionPredecessorUnavailable(PermissionError):
    """The active generation cannot authenticate this operation's predecessor."""


def effect_key(repo: str, branch: str, head: str, predecessor: str = "") -> str:
    from .publishing import _sha256

    canonical = f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0{publish_committed_branch_idempotency_key(repo, branch, head)}"
    if not predecessor:
        return canonical
    return f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0scope-correction-v1\0{_sha256(canonical.encode())}"


def _original(repo, lineage):
    from .publishing import (
        PublishTransactionState, _sha256, build_pre_trailer_intent,
        inspect_publish_resume_candidate,
    )

    candidate = inspect_publish_resume_candidate(
        repo, checkpoint_root=Path(lineage["checkpoint_root"]), node_id=lineage["node_id"],
    )
    original = candidate.transaction
    if candidate.state != PublishTransactionState.TERMINAL_SEALED or original is None or original.mode != "normal":
        raise PermissionError("scope correction requires an exact sealed normal predecessor")
    if original.transaction_id != lineage["predecessor_id"]:
        raise PermissionError("scope correction predecessor differs")
    if original.exact_ref != f"refs/heads/{original.branch}":
        raise PermissionError("original predecessor branch reference differs")
    # The immutable commit trailer commits to this complete original intent.
    # Merely comparing the successor to a mutable checkpoint would not prove
    # that its saved publication inputs still match the originally admitted work.
    inputs = {
        "schema": "PublishPreTrailerIntent.v1",
        "canonical_repository_identity": original.canonical_repository_identity,
        "branch": original.branch, "base": original.base,
        "base_tip_sha": original.base_tip_sha, "mode": original.mode,
        "parent_head_sha": original.parent_head_sha, "staged_tree_oid": original.tree_oid,
        "owned_paths": list(original.owned_paths), "staged_diff_sha256": original.staged_diff_sha256,
        "original_commit_message_length": len(original.original_commit_message_bytes),
        "original_commit_message_sha256": _sha256(original.original_commit_message_bytes),
        "draft": original.draft, "pr_body_sha256": _sha256(original.pr_body.encode("utf-8")),
        "envelope_authority_preimage": original.envelope_authority_preimage,
    }
    intent = build_pre_trailer_intent(inputs, original_message=original.original_commit_message_bytes)
    if any(getattr(intent, name) != getattr(original, name) for name in (
        "transaction_id", "pre_trailer_intent_sha256", "original_commit_message_sha256",
        "final_commit_message_sha256", "final_commit_message_bytes",
    )):
        raise PermissionError("original predecessor intent binding differs")
    return original


def validate_source(repo, transaction):
    """Read-only exact-object and unchanged-proof validation, also on replay."""
    from .publishing import _canonical_bytes, _git_bytes, _sha256

    lineage = transaction._payload.get("scope_correction")
    if transaction.mode != MODE or not isinstance(lineage, dict) or lineage.get("schema") != "PublishScopeCorrection.v1":
        raise PermissionError("invalid scope correction checkpoint")
    original = _original(repo, lineage)
    overrides = {"state", "mode", "checkpoint_root", "owned_paths", "scope_correction",
                 "transaction_id", "pre_trailer_intent_sha256", "envelope_authority_preimage", "node_id"}
    for name, value in original._payload.items():
        if name not in overrides and transaction._payload.get(name) != value:
            raise PermissionError(f"scope correction changed original metadata {name}")
    for name in ("canonical_repository_identity", "branch", "exact_ref", "base", "draft", "pr_body",
                 "expected_commit_oid", "committed_head_sha", "final_commit_object_sha256"):
        if getattr(transaction, name) != getattr(original, name):
            raise PermissionError(f"scope correction changed {name}")
    if not set(original.owned_paths) < set(transaction.owned_paths):
        raise PermissionError("scope correction must strictly extend original ownership")
    if transaction.envelope_authority_preimage.get("effective_code_digest") != _sha256(
        "\0".join(transaction.owned_paths).encode("utf-8", "surrogateescape")
    ):
        raise PermissionError("scope correction ownership digest differs")
    for name in ("action", "roadmap_digest", "dependency_digest", "verification_plan_digest",
                 "expected_version_predicate", "authority_domain_scope", "operation_identity"):
        if transaction.envelope_authority_preimage.get(name) != original.envelope_authority_preimage.get(name):
            raise PermissionError(f"scope correction changed proof binding {name}")
    raw = _git_bytes(repo, "cat-file", "commit", transaction.committed_head_sha)
    if raw is None or _sha256(raw) != original.final_commit_object_sha256:
        raise PermissionError("scope correction commit bytes differ")
    if transaction.final_commit_message_bytes != original.final_commit_message_bytes:
        raise PermissionError("scope correction changed original commit message")
    # Recompute the successor's lineage-bound identity instead of trusting a
    # caller-controlled predecessor label alongside an unrelated transaction.
    expected = _sha256(b"FABPUB-SCOPE-CORRECTION-v1\0" + _canonical_bytes({
        "lineage": lineage, "owned_paths": list(transaction.owned_paths),
        "authority": transaction.envelope_authority_preimage,
    }))
    if transaction.transaction_id != expected:
        raise PermissionError("scope correction identity differs")
    return original


def prepare(repo, *, original_checkpoint_root, original_node_id, checkpoint_root,
            owned_paths, branch, authority, base="main", draft=True, pr_body=""):
    """Prepare an exact existing-commit successor; never write a Git ref/object."""
    from .publishing import (
        PublishTransaction, PublishTransactionConflict, PublishTransactionState,
        PublishTransactionStore, _canonical_bytes, _git_bytes, _git_output,
        _human_publication_scope_precheck, _redact_publication_body, _sha256,
        inspect_publish_resume_candidate,
    )

    repo = Path(repo).resolve()
    candidate = inspect_publish_resume_candidate(repo, checkpoint_root=Path(original_checkpoint_root), node_id=original_node_id)
    original = candidate.transaction
    if candidate.state != PublishTransactionState.TERMINAL_SEALED or original is None:
        raise PermissionError("scope correction predecessor is unavailable or unresolved")
    if Path(checkpoint_root).resolve() == original.checkpoint_root.resolve():
        raise PermissionError("scope correction needs a distinct successor context")
    if _git_bytes(repo, "status", "--porcelain=v1", "-z") != b"":
        raise PermissionError("scope correction workspace must be clean")
    if _git_output(repo, "symbolic-ref", "-q", "HEAD") != original.exact_ref:
        raise PermissionError("scope correction branch differs")
    if _git_output(repo, "rev-parse", "HEAD") != original.committed_head_sha:
        raise PermissionError("scope correction HEAD must equal the original commit")
    scope = tuple(sorted(set(owned_paths)))
    error = _human_publication_scope_precheck(repo, scope, base=base, branch=branch)
    if error:
        raise PermissionError(error)
    lineage = {"schema": "PublishScopeCorrection.v1", "checkpoint_root": str(original.checkpoint_root),
               "node_id": original.store.node_id, "predecessor_id": original.transaction_id}
    transaction_id = _sha256(b"FABPUB-SCOPE-CORRECTION-v1\0" + _canonical_bytes({
        "lineage": lineage, "owned_paths": list(scope), "authority": authority,
    }))
    payload = dict(original._payload)
    payload.update(state=PublishTransactionState.COMMITTED_HEAD_RESOLVED, mode=MODE,
                   checkpoint_root=str(Path(checkpoint_root).resolve()), owned_paths=list(scope),
                   scope_correction=lineage, transaction_id=transaction_id,
                   pre_trailer_intent_sha256=transaction_id, envelope_authority_preimage=dict(authority),
                   base=base, branch=branch, draft=draft,
                   pr_body=_redact_publication_body(repo, pr_body, Path(checkpoint_root)))
    payload["node_id"] = authority["node_id"]
    # The original trailer remains byte-exact. It belongs to the predecessor;
    # generic prebuilt/normal preparation still rejects substituted trailers.
    payload["final_message_b64"] = base64.b64encode(original.final_commit_message_bytes).decode("ascii")
    store = PublishTransactionStore(Path(checkpoint_root), authority["node_id"])
    transaction = PublishTransaction(repo, store, payload)
    validate_source(repo, transaction)
    with store.exclusive():
        current = inspect_publish_resume_candidate(repo, checkpoint_root=Path(checkpoint_root), node_id=store.node_id)
        if current.transaction is not None:
            if current.state not in PublishTransactionState.ORDERED[2:] or current.transaction.transaction_id != transaction_id:
                raise PublishTransactionConflict("different scope correction already occupies the context")
            validate_source(repo, current.transaction)
            return current.transaction
        # Conflicting or corrupt active pointers must not be replaced.
        if store.load_active() is not None or store.sibling_active_pointers():
            raise PublishTransactionConflict("scope correction context has unresolved ownership")
        transaction._write()
        store.write_active(transaction_id)
    return transaction


def authorize(service, request):
    """Authenticate the predecessor and reserve one successor under broker lock.

    A reservation survives crashes. Conflicting corrections cannot create a
    second successor even when their checkpoint contexts differ.
    """
    from .convergence.broker import evidence
    from .publishing import _atomic_json, _canonical_bytes, _human_publication_scope_precheck, _read_json_nofollow, _sha256

    if request.verb is not BrokerVerb.PUBLISH_COMMITTED_BRANCH:
        raise PermissionError("scope correction only applies to publication")
    _envelope, transaction = service._validated_envelope(request)
    original = validate_source(Path(request.adapter_worktree), transaction)
    if request.scope_correction_of != original.transaction_id:
        raise PermissionError("request scope correction predecessor differs")
    if any(getattr(request, name) != getattr(transaction, name) for name in ("base", "draft", "pr_body")):
        raise PermissionError("scope correction request changed frozen publication inputs")
    error = _human_publication_scope_precheck(Path(request.adapter_worktree), request.owned_paths,
                                             base=request.base, branch=request.branch)
    if error:
        raise PermissionError(error)
    original_key = effect_key(request.repo, request.branch, request.head_sha)
    successor_key = effect_key(request.repo, request.branch, request.head_sha, original.transaction_id)
    binding = {"schema": "PublishScopeCorrectionReceipt.v1", "original_effect_key": original_key,
               "successor_effect_key": successor_key, "predecessor_id": original.transaction_id,
               "successor_id": transaction.transaction_id, "committed_head": request.head_sha,
               "commit_object_sha256": original.final_commit_object_sha256,
               "original_owned_paths": list(original.owned_paths), "corrected_owned_paths": list(transaction.owned_paths),
               "proof_authority": transaction.envelope_authority_preimage}
    path = service.evidence_store.root / ("scope-correction-" + _sha256(original_key.encode()) + ".json")
    service.evidence_store._authorize()
    with service.admission_store.lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            service.evidence_store._authorize()
            service.admission_store._records()
            records = service.evidence_store.replay()
            terminal = records.get(original_key)
            if terminal is None or terminal.state is not TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN or not terminal.evidence_reference.startswith("owned-scope-exceeded:"):
                raise ScopeCorrectionPredecessorUnavailable(
                    "scope correction requires an authenticated ownership-scope no-effect terminal "
                    "in the active generation; a partition rotation does not carry this "
                    "operation's predecessor/receipt binding. Preserve both checkpoints and "
                    "request supported predecessor-chain recovery; do not retry or attest "
                    "a new correction from remote absence."
                )
            binding["original_terminal_sha256"] = _sha256(_canonical_bytes(asdict(terminal)))
            existing = _read_json_nofollow(path)
            if existing is not None:
                if existing != binding:
                    raise PermissionError("a different scope correction is already reserved")
                return successor_key
            if service.evidence_store.epoch_blocked:
                raise PermissionError("scope correction cannot recover a blocked partition")
            owner = evidence.read_adapter_start_owner(service.evidence_store.root, repository_identity=request.repo)
            if owner is None or not owner.sealed or owner.effect_key != original_key or owner.transaction_id != original.transaction_id or owner.committed_head != request.head_sha:
                raise PermissionError("scope correction requires the exact sealed predecessor owner")
            _atomic_json(path, binding, mode=0o600)
            return successor_key
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
