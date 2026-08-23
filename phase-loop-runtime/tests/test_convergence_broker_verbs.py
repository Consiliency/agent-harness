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

    def _run_test():
        from phase_loop_runtime.convergence.broker.verbs import BrokerService
        from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
        from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
        from phase_loop_runtime.convergence.contracts import DeltaReadmitAuthority, DeltaReadmitReceipt

        adapter = _CountingAdapter()
        store = LinearizableAdmissionStore(tmp_path / "admissions", lambda _: True)
        evidence = BrokerEvidenceStore(tmp_path / "evidence")
        service = BrokerService(store, evidence, adapter, contracts=())

        auth = DeltaReadmitAuthority(
            repository="Consiliency/agent-harness",
            adapter_worktree=str(tmp_path / "repo"),
            checkpoint_root=str(tmp_path / "ckpt"),
            branch="feat/x",
            base="main",
            prior_head_sha="a" * 40,
            proposed_head_sha="b" * 40,
            train_id="train1",
            node_id="n1",
            fab_run_id="run1",
            roadmap_digest="d" * 64,
            provenance_digest="p" * 64,
            owned_scope=("pkg",),
        )

        receipt = service.readmit_advanced_head(auth)

        assert isinstance(receipt, DeltaReadmitReceipt)
        assert receipt.repository == "Consiliency/agent-harness"
        assert receipt.proposed_head_sha == "b" * 40
        assert receipt.allocated_epoch > 0
        assert adapter.calls == 0, "readmit_advanced_head verb must call zero provider adapters"

    valid = False
    try:
        _run_test()
        valid = True
    except Exception:
        valid = False

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid,
        "BrokerService.readmit_advanced_head verb missing or unvalidated",
    )
