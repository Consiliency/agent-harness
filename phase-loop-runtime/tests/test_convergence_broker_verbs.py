from _fabpub_tdd_guard import fabpub_migrated_activated
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
from phase_loop_runtime.convergence.broker.verbs import BrokerService, publish_committed_branch_idempotency_key
from phase_loop_runtime.convergence.contracts import AdmissionRequest, BrokerRequest, BrokerTerminalEvidence, BrokerVerb, PublishCommittedBranchResult
from phase_loop_runtime.convergence.provider_contracts import ProviderAutomationDisposition, ProviderCompletionClassification, ProviderCompletionContract


def test_publish_key_binds_the_canonical_triple():
    assert publish_committed_branch_idempotency_key("r", "b", "h") != publish_committed_branch_idempotency_key("r", "b", "other")


# --- Blocker 2: canonical-triple idempotency -------------------------------
# A test-local SUPPORTED contract reaches the live-capable path WITHOUT touching
# the global provider_contracts (which stays HUMAN_EXECUTED); the verb remains
# gated everywhere else.
_SUPPORTED_PCB = (
    ProviderCompletionContract(
        verb="publish_committed_branch",
        provider="github",
        classification=ProviderCompletionClassification.SUPPORTED,
        disposition=ProviderAutomationDisposition.AUTOMATED,
        status_endpoint="gh pr list",
        idempotency_key_supported="yes",
        terminal_success_evidence="remote head matches pushed sha",
        terminal_no_effect_evidence="no remote ref",
        non_late_commit_guarantee="fenced",
        guaranteed_processing_horizon="synchronous",
        expected_version_predicate="head == sha",
        revocation_affects_accepted="no",
        stabilization_drain_interval="0",
    ),
)

_CANONICAL_REPOSITORY_IDENTITY = "canonical-repository-identity"
_ADAPTER_WORKTREE = "repo"


class _CountingAdapter:
    def __init__(self):
        self.calls = 0

    def execute(self, request):
        self.calls += 1
        return (
            PublishCommittedBranchResult(request.branch, request.head_sha, f"https://gh/pr/{self.calls}"),
            BrokerTerminalEvidence(request.admission.idempotency_key, "effect_terminal_observed", "github-observed"),
        )


def _service(tmp_path, adapter):
    return BrokerService(
        LinearizableAdmissionStore(tmp_path, lambda _: True),
        BrokerEvidenceStore(tmp_path),
        adapter,
        contracts=_SUPPORTED_PCB,
    )


def _pcb_request(
    admission_key, *, repo=_CANONICAL_REPOSITORY_IDENTITY, branch="feat/x", head="abc123"
):
    admission = AdmissionRequest("attempt", 1, "fence", "digest", "predicate", "scope", admission_key)
    return BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, admission, repo, branch, head, ("a.py",))


def test_same_triple_twice_single_effect_and_identical_result(tmp_path, request):
    adapter = _CountingAdapter()
    if fabpub_migrated_activated(
        request,
        detail=(
            "a fresh publish still accepts a finalized AdmissionRequest; FABPUB requires "
            "PreAdmissionEnvelope plus admit_next for every fresh publish_committed_branch"
        ),
    ):
        from test_convergence_live_enable import _activated_publish_fixture

        # FABPUB replacement branch: canonical-triple de-dup is asserted through the
        # envelope + transaction handoff, and the caller may not stamp an epoch.
        _repo, root, publish = _activated_publish_fixture(
            tmp_path, label="verbs-dedup", branch="feat/x"
        )
        svc = _service(root, adapter)
        r1 = svc.execute(publish)
        r2 = svc.execute(publish)
        assert adapter.calls == 1, "canonical triple must de-dup: only a single effect"
        assert r2.publish_result == r1.publish_result
        assert r2.accepted
        return
    svc = _service(tmp_path, adapter)
    # Same (repo, branch, head_sha) under DIFFERENT admission keys.
    r1 = svc.execute(_pcb_request("key-1"))
    r2 = svc.execute(_pcb_request("key-2"))
    assert adapter.calls == 1, "canonical triple must de-dup: only a single effect"
    assert r1.publish_result is not None and r1.publish_result.pr_url == "https://gh/pr/1"
    assert r2.publish_result == r1.publish_result, "repeat returns the SAME prior result"
    assert r2.accepted


def test_replay_after_complete_returns_prior_result_not_none(tmp_path, request):
    adapter = _CountingAdapter()
    if fabpub_migrated_activated(
        request,
        detail=(
            "the FRESH arm of this replay still supplies a finalized AdmissionRequest, so the "
            "mandated TypeError fires before the replay is ever reached; FABPUB requires the "
            "fresh publish to use PreAdmissionEnvelope while terminal replay stays shape-agnostic"
        ),
    ):
        from test_convergence_live_enable import _activated_publish_fixture

        # Fresh publish uses the envelope; the COMPLETED terminal then replays through
        # BOTH shapes, because replay returns before authorization and performs no
        # admission or adapter call.
        _repo, root, publish = _activated_publish_fixture(
            tmp_path, label="verbs-replay", branch="feat/x"
        )
        svc = _service(root, adapter)
        first = svc.execute(publish)
        envelope_replay = svc.execute(publish)
        finalized_replay = svc.execute(
            _pcb_request(
                "key-late",
                repo=publish.repo,
                branch=publish.branch,
                head=publish.head_sha,
            )
        )
        assert adapter.calls == 1
        for replayed in (envelope_replay, finalized_replay):
            assert replayed.publish_result is not None, (
                "replay of a COMPLETED op must return the result, not None"
            )
            assert replayed.publish_result == first.publish_result
            assert replayed.accepted, "idempotent recovery is accepted, not blocked"
        return
    svc = _service(tmp_path, adapter)
    req = _pcb_request("key-1")
    first = svc.execute(req)
    replay = svc.execute(req)
    assert adapter.calls == 1
    assert replay.publish_result is not None, "replay of COMPLETED op must return the result, not None"
    assert replay.publish_result == first.publish_result
    assert replay.accepted, "idempotent recovery is accepted, not blocked"


def test_fabreadmit_readmit_advanced_head_verb(request, tmp_path):
    """BrokerService readmit_advanced_head verb."""
    import subprocess
    import pytest
    from pytest import skip

    from _fabreadmit_tdd_guard import (
        FABREADMIT_SKIP_REASON,
        fabreadmit_capability_active,
        fabreadmit_require,
        fabreadmit_symbol,
        fabreadmit_this_nodeid,
    )

    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    verb_symbol = fabreadmit_symbol(
        "phase_loop_runtime.convergence.broker.verbs", "BrokerService.readmit_advanced_head"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        verb_symbol is not None,
        "BrokerService.readmit_advanced_head verb missing in phase_loop_runtime.convergence.broker.verbs",
    )

    from phase_loop_runtime.convergence.broker.verbs import BrokerService
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
    from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, DeltaReadmitReceipt
    from test_fabpub_shared_epoch import (
        _authorized_publish_fixture,
        _publish_transaction_request,
        _service as _pub_service,
        _CountingAdapter,
    )

    # 1. FR-R5-01 & FR-R7-01 & FR-R7-02: Empty-store denial arm proving readmission from an empty onboarded store fails
    repo_empty, txn_empty, id_empty, root_empty = _authorized_publish_fixture(tmp_path, name="verbs-empty")
    empty_envelope = _publish_transaction_request(id_empty, "feat/x", txn_empty, repo_empty).admission
    store_empty = LinearizableAdmissionStore(root_empty, lambda _: True)
    pub_empty_adapter = _CountingAdapter()
    svc_empty_pub = BrokerService(store_empty, BrokerEvidenceStore(root_empty), pub_empty_adapter)
    ckpt_empty = txn_empty.checkpoint_root
    (ckpt_empty / "train.json").write_text(f'{{"train_id": "{empty_envelope.train_id}", "repository": "{id_empty}"}}', encoding="utf-8")
    (ckpt_empty / f"{empty_envelope.node_id}.json").write_text(f'{{"node_id": "{empty_envelope.node_id}"}}', encoding="utf-8")
    auth_empty = DeltaReadmitAuthority(
        repository=id_empty, adapter_worktree=str(repo_empty), checkpoint_root=str(ckpt_empty),
        branch="feat/x", base="main", prior_head_sha=txn_empty.committed_head_sha, proposed_head_sha="b" * 40,
        train_id=empty_envelope.train_id, node_id=empty_envelope.node_id, fab_run_id="run1", roadmap_digest=empty_envelope.roadmap_digest, provenance_digest="p" * 64, owned_scope=("a.py",)
    )
    readmit_empty_adapter = _CountingAdapter()
    svc_empty_readmit = BrokerService(store_empty, BrokerEvidenceStore(root_empty), readmit_empty_adapter)
    with pytest.raises((PermissionError, ValueError), match=r"(?i)prior|unadmitted|unknown|forged|empty"):
        svc_empty_readmit.readmit_advanced_head(auth_empty)
    assert len(store_empty.replay()) == 0
    assert len(readmit_empty_adapter.calls) == 0

    # 2. FR-R5-01 & FR-R7-02: Setup activated store partition & seed real authorized publish
    repo_dir, transaction, identity, store_root = _authorized_publish_fixture(tmp_path, name="verbs-repo")
    pub_adapter = _CountingAdapter()
    store = LinearizableAdmissionStore(store_root, lambda _: True)
    evidence = BrokerEvidenceStore(store_root)
    pub_svc = _pub_service(store_root, pub_adapter, store=store)

    branch = "feat/x"
    pub_req = _publish_transaction_request(identity, branch, transaction, repo_dir)
    admitted_envelope = pub_req.admission
    pub_res = pub_svc.execute(pub_req)
    assert pub_res.accepted, "prior publish transaction must be admitted"
    assert len(store.replay()) == 1

    ckpt = transaction.checkpoint_root
    (ckpt / "train.json").write_text(f'{{"train_id": "{admitted_envelope.train_id}", "repository": "{identity}"}}', encoding="utf-8")
    (ckpt / f"{admitted_envelope.node_id}.json").write_text(f'{{"node_id": "{admitted_envelope.node_id}"}}', encoding="utf-8")

    (repo_dir / "a.py").write_text("v2 advance\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "advance"], check=True)
    delta_sha = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()

    readmit_adapter = _CountingAdapter()
    service = BrokerService(store, evidence, readmit_adapter)

    auth = DeltaReadmitAuthority(
        repository=identity,
        adapter_worktree=str(repo_dir),
        checkpoint_root=str(ckpt),
        branch=branch,
        base="main",
        prior_head_sha=transaction.committed_head_sha,
        proposed_head_sha=delta_sha,
        train_id=admitted_envelope.train_id,
        node_id=admitted_envelope.node_id,
        fab_run_id="run1",
        roadmap_digest=admitted_envelope.roadmap_digest,
        provenance_digest="p" * 64,
        owned_scope=("a.py",),
    )

    receipt = service.readmit_advanced_head(auth)

    assert isinstance(receipt, DeltaReadmitReceipt)
    assert receipt.repository == identity
    assert receipt.proposed_head_sha == delta_sha
    assert receipt.allocated_epoch == 2
    assert len(readmit_adapter.calls) == 0
