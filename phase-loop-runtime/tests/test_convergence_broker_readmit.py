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
    evidence = BrokerEvidenceStore(tmp_path)
    return BrokerService(
        # `epoch_blocked` wired exactly as the production builders wire it, so revocation
        # is evaluated INSIDE the admission lock rather than racing it.
        LinearizableAdmissionStore(tmp_path, policy, epoch_blocked=lambda: evidence.epoch_blocked),
        evidence,
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


def _readmit(svc, *, new_head=NEW_HEAD, prior_head=PRIOR_HEAD, branch=BRANCH, node_id="node-a",
             scope="scope", **_ignored):
    """`next_epoch` is deliberately absent: the broker allocates it. `**_ignored` absorbs
    an accidental `next_epoch=` from a stale call site so it fails LOUDLY on the assertion
    rather than silently reintroducing caller control."""
    assert not _ignored, f"the caller no longer chooses the epoch: {sorted(_ignored)}"
    return svc.readmit_advanced_head(
        repo=REPO, branch=branch, train_id="train-1", node_id=node_id,
        prior_head_sha=prior_head, new_head_sha=new_head,
        approval=_approval(), expected_version_predicate="head == committed",
        authority_domain_scope=scope,
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

    first = _readmit(svc, new_head="sha-attempt-1")
    assert first.accepted is False
    assert svc.admission_store.replay() == (), "attempt 1 must not leave a poison record"

    second = _readmit(svc, new_head="sha-attempt-2-different-key")
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

    first = _readmit(svc)
    second = _readmit(svc)  # same advance, replayed

    assert first.accepted and second.accepted
    assert first.idempotency_key == second.idempotency_key
    matching = [r for r in svc.admission_store.replay() if r.request.idempotency_key == first.idempotency_key]
    assert len(matching) == 1, "a resume must NOT append a second admission record"


def test_foreign_tenant_admission_does_not_baseline_this_readmit(tmp_path):
    """CR-2 finding 2. The in-lock baseline required only that SOME record existed, so a
    partial restore retaining an unrelated tenant's admission plus this target's publish
    evidence would be admitted. It must require a record from THIS authority.

    This is the case the truncation test does NOT cover: the log is non-empty, but nothing
    in it belongs to us. Mutation: revert the precondition to `if not records` -> passes.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted                      # writes evidence AND an admission
    svc.admission_store.path.write_text("", encoding="utf-8")   # lose OUR admission history

    foreign = AdmissionRequest("attempt-foreign", 1, "fence", "digest", "predicate",
                               "some-other-tenant", "foreign-key")
    svc.admission_store.admit(foreign)                 # a surviving UNRELATED record
    assert len(svc.admission_store.replay()) == 1

    with pytest.raises(PermissionError, match="no_admission_baseline"):
        _readmit(svc)


def test_conflicting_request_under_the_same_key_raises_value_error(tmp_path):
    """M5, explicitly required by the plan and missing from round 1: the store raises
    ValueError (not PermissionError) when a DIFFERENT request arrives under an already
    admitted idempotency key. The verb must not catch it — Change B maps it to None.

    Mutation: catch Exception around `admit` in the verb -> this fails.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted
    accepted = _readmit(svc)
    assert accepted.accepted

    admitted = next(r for r in svc.admission_store.replay()
                    if r.request.idempotency_key == accepted.idempotency_key)
    forged = AdmissionRequest(
        admitted.request.attempt_id, admitted.request.lease_epoch, admitted.request.fence_token,
        "a-DIFFERENT-approval-digest", admitted.request.expected_version_predicate,
        admitted.request.authority_domain_scope, admitted.request.idempotency_key,
    )
    with pytest.raises(ValueError):
        svc.admission_store.admit(forged)


def test_revocation_is_evaluated_inside_the_admission_lock(tmp_path):
    """CR-2 finding 3. Checking `epoch_blocked` only in the verb races
    `BrokerEvidenceStore._append`, which records a permanent block WITHOUT the admission
    lock — a block could land between the check and the append and still be accepted.

    The store's own `epoch_blocked` hook runs inside the lock; production now wires it.
    Mutation: construct `LinearizableAdmissionStore` without `epoch_blocked=` (as both
    builders did before this round) -> the admission is accepted on a blocked epoch.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted

    class _Boom:
        def execute(self, request): raise RuntimeError("provider blew up")

    svc.adapter = _Boom()
    _publish(svc, head="sha-will-blow", key="pub-boom")
    assert svc.evidence_store.epoch_blocked

    # Bypass the verb's own pre-store gate to prove the STORE refuses independently.
    factory = FencedAdmissionFactory()
    lease = factory.lease(train_id="t", node_id="n", action="readmit", lease_epoch=9,
                          attempt_id="a" * 32)
    request = factory.create(
        lease=lease, approval=_approval(),
        expected_version_predicate="head == committed", authority_domain_scope="scope",
    )
    with pytest.raises(PermissionError):
        svc.admission_store.admit(request)


def test_prefix_colliding_tenant_does_not_baseline_this_readmit(tmp_path):
    """Self-caught while hardening CR-2 finding 2: a bare `startswith` on the authority
    domain lets `"train-1"` prefix-match `"train-10\\0readmit\\0node-x"`, so a DIFFERENT
    tenant's admission would baseline this readmit — reopening the finding it was meant to
    close. Authority scopes are caller-supplied free text, so this is reachable, not
    theoretical.

    Mutation: revert `_ours` to a bare `scope.startswith(authority_domain_scope)` -> the
    foreign record baselines us and no PermissionError is raised.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted
    svc.admission_store.path.write_text("", encoding="utf-8")

    # A neighbouring tenant whose scope merely PREFIX-matches ours ("scope" vs "scope-2").
    neighbour = AdmissionRequest("attempt-neighbour", 1, "fence", "digest", "predicate",
                                 "scope-2\0readmit\0node-x", "neighbour-key")
    svc.admission_store.admit(neighbour)

    with pytest.raises(PermissionError, match="no_admission_baseline"):
        _readmit(svc)  # authority_domain_scope="scope"


# --- CR round 3: the caller controls NEITHER the epoch NOR its lineage ---------------

def test_epoch_is_allocated_by_the_broker_and_is_strictly_monotonic(tmp_path):
    """Replaces the old equal-epoch test, which asserted a rule that no longer exists.

    The caller supplies no epoch at all, so "strictly above" is not a check that can be
    weakened — it is a property of allocation. Mutation: allocate `max(...)` instead of
    `max(...)+1` -> the second advance collides.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted
    first = _readmit(svc, new_head="advance-1")
    second = _readmit(svc, new_head="advance-2")

    assert first.accepted and second.accepted
    assert second.granted_epoch > first.granted_epoch
    # ...and strictly above the PUBLISH's own epoch (CR-3 finding 3a: a first readmit
    # used to be admissible at epoch 1, the same epoch the publish sat at).
    publish_epoch = min(r.epoch for r in svc.admission_store.replay())
    assert first.granted_epoch > publish_epoch


def test_two_nodes_in_one_repo_never_fence_each_other(tmp_path):
    """CR-3 finding 3b: node A advancing to a high epoch used to make node B's LEGITIMATE
    first readmit fail the store's repo-global stale check with `stale epoch`. Verified
    empirically before this rewrite. With broker allocation, node B simply receives the
    next number.

    Mutation: reinstate a caller-supplied epoch -> node B must guess, and guessing low
    fails while guessing high breaks monotonicity.
    """
    svc = _service(tmp_path)
    assert _publish(svc, branch="feat/node-a", head="sha-a-prior", key="pub-a").accepted
    assert _publish(svc, branch="feat/node-b", head="sha-b-prior", key="pub-b").accepted

    # Node A runs well ahead.
    for i in range(3):
        assert _readmit(svc, node_id="node-a", branch="feat/node-a",
                        prior_head="sha-a-prior", new_head=f"a{i}").accepted

    b = _readmit(svc, node_id="node-b", branch="feat/node-b",
                 prior_head="sha-b-prior", new_head="b0")
    assert b.accepted, "a lagging node's first readmit must not be fenced by a faster one"


def test_a_fresh_node_identity_buys_nothing(tmp_path):
    """CR-3 finding 2, the fail-open that drove this redesign: when the caller declares
    its own identity AND picks its own epoch, it can always present an unused identity,
    have no history, and walk past a "higher than your last" rule.

    Identity is now irrelevant to fencing — the epoch is global and broker-allocated — so
    inventing one gains nothing. Mutation: key allocation off a caller-scoped lineage
    again -> the invented identity restarts at 1 and this fails.
    """
    svc = _service(tmp_path)
    assert _publish(svc).accepted
    real = _readmit(svc, node_id="node-a", new_head="advance-1")

    invented = _readmit(svc, node_id="totally-made-up-node", new_head="advance-2")

    assert invented.granted_epoch > real.granted_epoch, (
        "an invented node identity must not reset the fence"
    )


def test_attempt_id_is_delimited_and_epoch_free(tmp_path):
    """The attempt id must NOT encode the epoch: a resume has to find its own earlier
    record before an epoch is allocated, or it is handed a fresh number and never de-dups.
    Delimiting still matters — ('a','bc') must not collide with ('ab','c')."""
    assert readmit_attempt_id("a", "bc") != readmit_attempt_id("ab", "c")
    assert readmit_attempt_id("n", "s") == readmit_attempt_id("n", "s")

    svc = _service(tmp_path)
    assert _publish(svc).accepted
    first = _readmit(svc, new_head="same-advance")
    again = _readmit(svc, new_head="same-advance")
    assert first == again, "a resume must return the SAME record, not a freshly allocated epoch"
    assert len(svc.admission_store.replay()) == 2, "publish + exactly one readmit"


def test_a_concurrent_revocation_cannot_land_mid_admission(tmp_path):
    """CR-3 finding 1, and the one my first attempt failed to actually test.

    Moving the `epoch_blocked` check inside the admission lock is NOT sufficient while the
    evidence writer takes no lock at all: a block can still become durable between the
    check and the append. codex's words: 'both operations need a common serialization
    boundary.' Pre-seeding a block (what the earlier test did) proves nothing about the
    interleaving.

    This drives the interleaving directly: while the admission lock is held, a second
    thread attempts to write blocked evidence. With a shared lock it MUST be unable to
    complete inside that window; it completes as soon as the admission releases.

    Mutation: give the evidence store its own lock file -> the writer sails through mid
    admission and this fails.
    """
    import threading

    svc = _service(tmp_path)
    assert _publish(svc).accepted

    landed = threading.Event()
    entered = threading.Event()

    def _block_the_epoch():
        entered.wait(timeout=5)
        svc.evidence_store.rejected_before_start("racing-key", "concurrent-revocation")
        landed.set()

    writer = threading.Thread(target=_block_the_epoch, daemon=True)
    writer.start()

    observed_during_window = {}
    real_precondition_point = svc.admission_store.admit_next

    def _instrumented(make_request, *, attempt_id, precondition=None):
        def _wrapped(records):
            entered.set()                     # we are INSIDE the admission lock now
            landed.wait(timeout=0.5)          # give the writer every chance to slip in
            observed_during_window["landed"] = landed.is_set()
            return precondition(records) if precondition else None
        return real_precondition_point(make_request, attempt_id=attempt_id, precondition=_wrapped)

    svc.admission_store.admit_next = _instrumented
    result = _readmit(svc)
    writer.join(timeout=5)

    assert observed_during_window["landed"] is False, (
        "a revocation landed while the admission lock was held — the stores are not "
        "sharing a serialization boundary"
    )
    assert result.accepted
    assert landed.is_set(), "the writer must proceed once the admission releases the lock"
