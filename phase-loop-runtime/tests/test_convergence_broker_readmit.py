"""ah#288 Change A — the decoupled-admit broker primitive (`readmit_advanced_head`).

Re-admit an ADVANCED head WITHOUT publishing (the advance is already pushed). This is a
TRUST-ROOT gate: a branch that fails OPEN admits an unreviewed head. Every branch below
drives the production `BrokerService` against file-backed stores and states the mutation
that kills it.

The #288 CR (codex DISAGREE / grok PARTIALLY AGREE) established two things the original
plan got wrong, both covered here:

  A1  A post-admit `sequence >= 2` baseline does NOT close the empty-store fail-open.
      `admit` appends sequence 1 unconditionally, so the caller's OWN write satisfies the
      test on a retry — see `test_poison_record_retry_is_refused`, the exploit itself.
      Baseline validation must therefore run INSIDE the store lock, BEFORE mutation.

  A2  The store rejects only `lease_epoch < max`, so a DIFFERENT request at the CURRENT
      epoch is admissible — contradicting this verb's strictly-above contract.

TWO REFUSAL CHANNELS — both fail closed, and the seam must handle both:
  * checks BEFORE the store (revocation, prior-publish baseline) RETURN
    `ReadmitResult(accepted=False, reason=...)`;
  * denials INSIDE the store's lock (the precondition, the store's own fencing, the
    admission policy) RAISE `PermissionError`/`ValueError`, which this verb deliberately
    does not catch — Change B maps them to `None` and recovers the admitted prefix.

      IMPLEMENTATION NOTE (a refinement of the CR's prescription, verified before
      applying): the CR suggested tightening `LinearizableAdmissionStore` to reject
      `<= max`. That would REGRESS the publish path — every publish admits at
      `lease_epoch=1` (`train_runner` builds `action="publish"` leases with a literal 1),
      so an N-node train holds N distinct admissions at epoch 1 and node 2 would raise
      `stale epoch`. `test_multi_node_same_epoch_publishes_still_admit` pins that, and the
      strictly-above rule lives in the readmit verb where it belongs.
"""
from __future__ import annotations

import pytest

from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
from phase_loop_runtime.convergence.broker.verbs import (
    BrokerService,
    ReadmitResult,
    readmit_attempt_id,
)
from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    BrokerRequest,
    BrokerTerminalEvidence,
    BrokerVerb,
    PublishCommittedBranchResult,
)
from phase_loop_runtime.convergence.fencing import FencedAdmissionFactory
from phase_loop_runtime.convergence.provider_contracts import (
    ProviderAutomationDisposition,
    ProviderCompletionClassification,
    ProviderCompletionContract,
)

_SUPPORTED_PCB = (
    ProviderCompletionContract(
        verb="publish_committed_branch", provider="github",
        classification=ProviderCompletionClassification.SUPPORTED,
        disposition=ProviderAutomationDisposition.AUTOMATED,
        status_endpoint="gh pr list", idempotency_key_supported="yes",
        terminal_success_evidence="remote head matches pushed sha",
        terminal_no_effect_evidence="no remote ref", non_late_commit_guarantee="fenced",
        guaranteed_processing_horizon="synchronous",
        expected_version_predicate="head == sha", revocation_affects_accepted="no",
        stabilization_drain_interval="0",
    ),
)

REPO, BRANCH, PRIOR_HEAD, NEW_HEAD = "repo", "feat/x", "sha-prior", "sha-advanced"


class _PublishAdapter:
    def __init__(self): self.calls = 0
    def execute(self, request):
        self.calls += 1
        return (
            PublishCommittedBranchResult(request.branch, request.head_sha, f"https://gh/pr/{self.calls}"),
            BrokerTerminalEvidence(request.admission.idempotency_key, "effect_terminal_observed", "github-observed"),
        )


def _service(tmp_path, *, policy=lambda _: True):
    return BrokerService(
        LinearizableAdmissionStore(tmp_path, policy),
        BrokerEvidenceStore(tmp_path),
        _PublishAdapter(),
        contracts=_SUPPORTED_PCB,
    )


def _approval():
    return FencedAdmissionFactory().approval(
        roadmap_digest="rd", effective_code="ec", base_sha="bs", dependency_shas=(),
        verification_plan_digest="vp", verification_artifact_digest="va",
    )


def _publish(svc, *, branch=BRANCH, head=PRIOR_HEAD, key="pub-1", epoch=1):
    """Drive a REAL publish through `execute`, so the baseline the readmit looks for is
    written by production code rather than hand-forged into the store."""
    admission = AdmissionRequest("attempt-pub", epoch, "fence", "digest", "predicate", "scope", key)
    return svc.execute(BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, admission, REPO, branch, head, ("a.py",)))


def _readmit(svc, *, next_epoch=2, new_head=NEW_HEAD, prior_head=PRIOR_HEAD, branch=BRANCH, node_id="node-a"):
    return svc.readmit_advanced_head(
        repo=REPO, branch=branch, train_id="train-1", node_id=node_id,
        prior_head_sha=prior_head, new_head_sha=new_head, next_epoch=next_epoch,
        approval=_approval(), expected_version_predicate="head == committed",
        authority_domain_scope="scope",
    )


# --- the accepting path (without it, every fail-closed test below is vacuous) ------

def test_readmit_accepted_after_a_completed_publish(tmp_path):
    """POSITIVE CONTROL. Mutation: make the verb return a hardcoded refusal and every
    other test in this file still passes."""
    svc = _service(tmp_path)
    assert _publish(svc).accepted

    result = _readmit(svc)

    assert result == ReadmitResult(True, 2, result.idempotency_key)
    assert result.idempotency_key, "an accepted readmit must name the key it admitted under"
    durable = [r for r in svc.admission_store.replay() if r.request.idempotency_key == result.idempotency_key]
    assert len(durable) == 1 and durable[0].epoch == 2, "the admission must be DURABLE at the granted epoch"


# --- A1: the baseline must precede mutation ---------------------------------------

def test_empty_store_is_refused(tmp_path):
    """M2. `admit`'s `if records and ...` short-circuit skips epoch fencing entirely on an
    empty log. Mutation: drop the `if not records` clause from the precondition."""
    svc = _service(tmp_path)
    result = _readmit(svc)
    assert result.accepted is False
    assert result.reason == "no_prior_publish"
    assert svc.admission_store.replay() == (), "a refused readmit must not mutate the log"


def test_poison_record_retry_is_refused(tmp_path):
    """THE ah#288 CR A1 EXPLOIT, verbatim: 'a replacement PR head produces a different key
    at epoch 2, appends sequence 2, and is accepted although no publish ever occurred.'

    A post-admit `sequence >= 2` baseline passes on this second attempt, because attempt
    one wrote sequence 1. The precondition runs before any append, so attempt one leaves
    the log empty and attempt two is refused on the same grounds.

    Mutation: move the baseline check after `admission_store.admit(...)` — attempt two
    then reports accepted.
    """
    svc = _service(tmp_path)

    first = _readmit(svc, new_head="sha-attempt-1", next_epoch=2)
    assert first.accepted is False
    assert svc.admission_store.replay() == (), "attempt 1 must not leave a poison record"

    second = _readmit(svc, new_head="sha-attempt-2-different-key", next_epoch=2)
    assert second.accepted is False, "the retry exploited a record its own first attempt wrote"
    assert svc.admission_store.replay() == ()


def test_lost_admission_log_is_refused_even_though_evidence_survives(tmp_path):
    """The ORIGINAL ah#288 fail-open, at its root: `admit`'s `if records and ...`
    short-circuit means an EMPTY log skips epoch fencing entirely, so the first record
    written sets the baseline epoch. Log durability is therefore silently load-bearing.

    The admission log and the evidence log are SEPARATE files. Truncation, rotation, or
    partial restore can leave a completed publish in evidence with no admission history —
    the one state where the pre-store baseline passes and the empty-log clause is the only
    thing standing. Mutation: drop `if not records` from the precondition -> this admits
    at an unfenced epoch.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted
    assert svc.admission_store.replay(), "fixture precondition: the publish wrote a record"

    svc.admission_store.path.write_text("", encoding="utf-8")  # log lost; evidence intact
    assert svc.admission_store.replay() == ()
    assert svc.evidence_store.epoch_blocked is False

    with pytest.raises(PermissionError, match="no_admission_baseline"):
        _readmit(svc)

    assert svc.admission_store.replay() == (), "a refused readmit must not seed a new baseline"


def test_baseline_is_bound_to_the_exact_repo_branch_and_prior_head(tmp_path):
    """'Not merely any earlier record.' A completed publish for a DIFFERENT branch must
    not baseline this readmit. Mutation: key the baseline on repo alone."""
    svc = _service(tmp_path)
    assert _publish(svc, branch="feat/unrelated", key="pub-other").accepted

    assert _readmit(svc).reason == "no_prior_publish"
    # ...and a publish of a different HEAD on the right branch is equally not a baseline.
    assert _publish(svc, head="sha-some-other-head", key="pub-other-head").accepted
    assert _readmit(svc).reason == "no_prior_publish"


# --- A2: strictly above ------------------------------------------------------------

def test_equal_epoch_conflicting_readmission_is_refused(tmp_path):
    """ah#288 CR A2. The store rejects only `lease_epoch < max`, so a DIFFERENT request at
    the CURRENT epoch would otherwise be admitted.

    Surfaces on the RAISING channel (see the module docstring's two-channel note): the
    precondition runs inside `admit`, and a denial there is a `PermissionError` exactly
    like the store's own fencing. Mutation: change the precondition's `<=` to `<` — no
    exception is raised and the conflicting advance is admitted.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted
    assert _readmit(svc, next_epoch=2).accepted

    with pytest.raises(PermissionError, match="epoch_not_advanced"):
        _readmit(svc, next_epoch=2, new_head="sha-a-different-advance")

    admitted_at_2 = [r for r in svc.admission_store.replay() if r.epoch == 2]
    assert len(admitted_at_2) == 1, "the conflicting advance must not have been appended"


def test_multi_node_same_epoch_publishes_still_admit(tmp_path):
    """REGRESSION GUARD for the refinement in this module's docstring: every publish
    admits at `lease_epoch=1`, so tightening the SHARED store to reject `<= max` would
    fail every node after the first. Mutation: move the strictly-above rule out of the
    readmit precondition and into `LinearizableAdmissionStore.admit` — this fails."""
    svc = _service(tmp_path)
    assert _publish(svc, branch="feat/node-a", head="sha-a", key="pub-a", epoch=1).accepted
    assert _publish(svc, branch="feat/node-b", head="sha-b", key="pub-b", epoch=1).accepted
    assert _publish(svc, branch="feat/node-c", head="sha-c", key="pub-c", epoch=1).accepted


# --- M4: revocation ----------------------------------------------------------------

def test_revoked_epoch_is_refused_before_any_admission(tmp_path):
    """M4. `epoch_blocked` is durable and permanent. Mutation: delete the revocation gate
    — the readmit then proceeds on a store already fail-closed."""
    svc = _service(tmp_path)
    assert _publish(svc).accepted

    # Reach the blocked state the way production does — an adapter exception on a publish
    # records OUTCOME_AMBIGUOUS_BLOCKED — rather than hand-forging the evidence record.
    class _Boom:
        def execute(self, request): raise RuntimeError("provider blew up")

    svc.adapter = _Boom()
    _publish(svc, head="sha-will-blow", key="pub-boom")
    assert svc.evidence_store.epoch_blocked, "fixture precondition: the epoch must be blocked"

    result = _readmit(svc)

    assert result.accepted is False
    assert result.reason == "revoked"


# --- exception propagation (M3/M5) --------------------------------------------------

def test_store_refusal_propagates_as_permission_error(tmp_path):
    """M3/M5: the verb catches NOTHING from the store. The seam caller maps these to a
    `None` result and recovers the admitted prefix; swallowing them here would report a
    refusal as a clean outcome. Mutation: wrap `admit` in try/except -> this fails."""
    svc = _service(tmp_path)
    assert _publish(svc).accepted  # clear the pre-store baseline, so we REACH the store
    svc.admission_store.policy = lambda _: False  # now the store denies inside its lock

    with pytest.raises(PermissionError):
        _readmit(svc)


# --- idempotent resume (A6) ---------------------------------------------------------

def test_resume_of_the_same_advance_is_idempotent(tmp_path):
    """A6. The attempt id is derived from (node_id, new_head_sha, next_epoch), so a resume
    of the SAME advance reproduces the SAME idempotency key and de-dups rather than
    admitting twice. Mutation: make `readmit_attempt_id` random -> a second call appends a
    second record (and then trips strictly-above), so this fails."""
    svc = _service(tmp_path)
    assert _publish(svc).accepted

    first = _readmit(svc, next_epoch=2)
    second = _readmit(svc, next_epoch=2)  # same advance, replayed

    assert first.accepted and second.accepted
    assert first.idempotency_key == second.idempotency_key
    matching = [r for r in svc.admission_store.replay() if r.request.idempotency_key == first.idempotency_key]
    assert len(matching) == 1, "a resume must NOT append a second admission record"


def test_attempt_id_is_delimited_and_domain_tagged():
    """The fields are variable-length; plain concatenation would let ('a','bc') collide
    with ('ab','c')."""
    assert readmit_attempt_id("a", "bc", 1) != readmit_attempt_id("ab", "c", 1)
    assert readmit_attempt_id("n", "s", 1) != readmit_attempt_id("n", "s", 2)
    assert readmit_attempt_id("n", "s", 1) == readmit_attempt_id("n", "s", 1)
