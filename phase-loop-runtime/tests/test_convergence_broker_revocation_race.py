"""ah#288 / #199: the broker admission vs. evidence-revocation race.

`BrokerService.execute` has had a check-then-admit shape since 6ff8c8a (#199): it
reads `evidence_store.epoch_blocked` (verbs.py) and THEN calls
`admission_store.admit`. A concurrent revocation — an `outcome_ambiguous_blocked`
evidence write — can become durable between the check and the admit, so a publish is
admitted into an epoch that has just been permanently revoked.

Closing it needs TWO things, and either alone is inert:

  (A) the evidence writer must take the SAME lock the admission store uses, so a
      revocation cannot land while an admission is being decided; and
  (B) the admission store must actually CONSULT the evidence under that lock —
      `LinearizableAdmissionStore.admit` already re-checks `self.epoch_blocked()`
      inside its lock, but production wired that callable to `lambda: False`, so the
      re-check saw nothing. `build_*` now wires it to `evidence_store.epoch_blocked`.

This module proves both halves independently, and that each is reproducible on the
pre-fix tree.  It is deliberately NOT about epoch ALLOCATION (ah#363): no
`admit_next`, no `lease_epoch` change, no re-admission verb.
"""
from __future__ import annotations

import json
import threading

import pytest

from _fabpub_tdd_guard import (
    fabpub_marker_version,
    fabpub_migrated_activated,
)
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore, EvidenceRecord
from phase_loop_runtime.convergence.broker.live import (
    build_github_broker_client,
    build_routing_broker_client,
)
from phase_loop_runtime.convergence.broker.verbs import BrokerService
from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    BrokerRequest,
    BrokerTerminalEvidence,
    BrokerVerb,
    PublishCommittedBranchResult,
)
from phase_loop_runtime.convergence.provider_contracts import (
    ProviderAutomationDisposition,
    ProviderCompletionClassification,
    ProviderCompletionContract,
    TerminalOutcomeState,
)

# A test-local SUPPORTED contract so `execute` reaches the admit path WITHOUT touching
# the global (HUMAN_EXECUTED) provider_contracts — the verb stays gated everywhere else.
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
    """Records whether the provider mutation was ever reached."""

    def __init__(self):
        self.calls = 0

    def execute(self, request):
        self.calls += 1
        return (
            PublishCommittedBranchResult(request.branch, request.head_sha, f"https://gh/pr/{self.calls}"),
            BrokerTerminalEvidence(request.admission.idempotency_key, "effect_terminal_observed", "github-observed"),
        )


def _service(tmp_path, adapter):
    """A BrokerService wired the way `build_*` wires production after this fix: the
    admission store's `epoch_blocked` reads the SAME evidence store the service records
    to.  Both stores share `tmp_path`, so they share `tmp_path/admissions.lock`.
    """
    evidence_store = BrokerEvidenceStore(tmp_path)
    admission_store = LinearizableAdmissionStore(
        tmp_path, lambda _req: True, epoch_blocked=lambda: evidence_store.epoch_blocked
    )
    return BrokerService(admission_store, evidence_store, adapter, contracts=_SUPPORTED_PCB)


def _pcb_request(
    admission_key="adm-1",
    *,
    repo=_CANONICAL_REPOSITORY_IDENTITY,
    adapter_worktree=_ADAPTER_WORKTREE,
    branch="feat/x",
    head="abc123",
):
    admission = AdmissionRequest("attempt", 1, "fence", "digest", "predicate", "scope", admission_key)
    return BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, admission, repo, branch, head, ("a.py",))


# --- (B) live wiring: the admission store must consult the evidence store ------------
#
# The load-bearing production edit. On the pre-fix tree `build_*` constructs the store
# with the default `epoch_blocked=lambda: False`, so a revoked epoch reads as open at the
# admission layer. Mutation to kill: drop `epoch_blocked=evidence_store.epoch_blocked`
# at either `build_*` site -> these fail.

from .proofgate_content_tdd_adapter import assert_exact_mutation_observable, emit_mutation_observable


def _assert_ec4_oracle_descriptor(param_id: str, expected_assertion_id: str) -> None:
    """Keep the two plan-frozen assertion IDs independent of source anchors."""
    properties: list[tuple[str, str]] = []
    emit_mutation_observable(param_id, lambda name, value: properties.append((name, value)))
    assert_exact_mutation_observable(param_id, properties)
    observable = json.loads(properties[0][1])
    assert observable["assertion_id"] == expected_assertion_id

    with pytest.raises(AssertionError, match="exactly one canonical property"):
        assert_exact_mutation_observable(param_id, [])
    with pytest.raises(AssertionError, match="exactly one canonical property"):
        assert_exact_mutation_observable(param_id, properties * 2)

    for bad_assertion_id in ("", "PG-A-BROKER-GITHUB", "PG-A-BROKER-ROUTING", "github_builder_epoch_blocked_wiring_synthesized"):
        tampered = dict(observable)
        tampered["assertion_id"] = bad_assertion_id
        with pytest.raises(AssertionError, match="mutation observable mismatch"):
            assert_exact_mutation_observable(
                param_id,
                [("proofgate_mutation_observable", json.dumps(tampered, sort_keys=True))],
            )


def _assert_wired(service, record_property, *, param_id=None, monkeypatch=None):
    ev = service.evidence_store
    assert service.admission_store.epoch_blocked() is False
    if fabpub_marker_version() == 1:
        from phase_loop_runtime.convergence.broker import live

        assert monkeypatch is not None
        monkeypatch.setattr(live, "load_partition_receipt", lambda _root: object())
        monkeypatch.setattr(
            live,
            "require_current_generation",
            lambda _root, _lease=None, *, strict=True: None,
        )
    ev.record_intent("k")
    ev.record_terminal(EvidenceRecord("k", TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "revoked"))
    assert ev.epoch_blocked is True
    cond = (service.admission_store.epoch_blocked() is True)
    if not cond and record_property is not None and param_id is not None:
        emit_mutation_observable(param_id, record_property)
    assert cond, (
        "the admission store must read the evidence store's revocation flag under its lock; "
        "an unwired store (lambda: False) admits into a revoked epoch"
    )


def test_github_broker_admission_store_is_wired_to_evidence_revocation(
    tmp_path, record_property, monkeypatch
):
    from .proofgate_content_tdd_adapter import ProofgateMissingCapabilityError, guard_proofgate_nodeid, run_proofgate_contract
    nodeid = "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import verification_evidence
        kwargs = {"_test_only_explicit_root": True} if fabpub_marker_version() == 1 else {}
        service = build_github_broker_client(
            tmp_path / "repo", broker_root=tmp_path / "broker", **kwargs
        )
        _assert_ec4_oracle_descriptor(
            "ec-proofgate-4.github-builder-epoch-blocked",
            "github_builder_epoch_blocked_wiring",
        )
        _assert_wired(
            service,
            record_property,
            param_id="ec-proofgate-4.github-builder-epoch-blocked",
            monkeypatch=monkeypatch,
        )
        if not hasattr(verification_evidence, "verify_proofgate_mutation_bindings"):
            raise ProofgateMissingCapabilityError("verify_proofgate_mutation_bindings interface missing on verification_evidence")

    run_proofgate_contract(nodeid, _contract)


def test_routing_broker_admission_store_is_wired_to_evidence_revocation(
    tmp_path, record_property, monkeypatch
):
    from .proofgate_content_tdd_adapter import ProofgateMissingCapabilityError, guard_proofgate_nodeid, run_proofgate_contract
    nodeid = "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import verification_evidence
        if fabpub_marker_version() == 1:
            from phase_loop_runtime.convergence.broker.live import (
                _test_only_repository_broker_client,
            )

            client = _test_only_repository_broker_client(tmp_path / "broker")
        else:
            client = build_routing_broker_client(broker_root=tmp_path / "broker")
        service = client._service_for(str(tmp_path / "repo"))
        _assert_ec4_oracle_descriptor(
            "ec-proofgate-4.routing-builder-epoch-blocked",
            "routing_builder_epoch_blocked_wiring",
        )
        _assert_wired(
            service,
            record_property,
            param_id="ec-proofgate-4.routing-builder-epoch-blocked",
            monkeypatch=monkeypatch,
        )
        if not hasattr(verification_evidence, "verify_proofgate_mutation_bindings"):
            raise ProofgateMissingCapabilityError("verify_proofgate_mutation_bindings interface missing on verification_evidence")

    run_proofgate_contract(nodeid, _contract)


# --- (B) end-to-end: execute refuses a publish when a revocation precedes admit -------
#
# Sequential (no threads): the revocation becomes durable AFTER execute's pre-check but
# BEFORE admit appends — exactly the check-then-admit window. With the store consulting
# evidence under its lock, admit raises and the provider is never called. Mutation to
# kill: delete admit's `self.epoch_blocked()` guard -> the publish goes through.

def test_execute_refuses_publish_when_revocation_becomes_durable_before_admit(tmp_path, request):
    adapter = _CountingAdapter()

    _fabpub = fabpub_migrated_activated(
        request,
        symbol=("phase_loop_runtime.convergence.broker.admission", "LinearizableAdmissionStore.admit_next"),
        detail=(
            "the revocation race is still injected at legacy admit(); FABPUB routes every "
            "fresh publish through admit_next, so the injection must move there"
        ),
    )
    if _fabpub:
        from test_convergence_live_enable import _activated_publish_fixture

        _repo, root, publish = _activated_publish_fixture(
            tmp_path, label="race-before-admit", branch="feat/x"
        )
    else:
        root, publish = tmp_path, _pcb_request()
    svc = _service(root, adapter)
    # FABPUB: a fresh publish allocates through admit_next, so the racing revocation
    # must be injected at THAT boundary; the legacy admit() seam only serves
    # non-publish verbs after migration.
    _admit_attr = "admit_next" if _fabpub else "admit"
    real_admit = getattr(svc.admission_store, _admit_attr)
    state = {"fired": False}

    def _admit_after_a_revocation_lands(request, *args, **kwargs):
        # Models the OS scheduling execute() out after its epoch_blocked pre-check: a
        # revocation (a durable outcome_ambiguous_blocked record) lands, THEN admit runs.
        if not state["fired"]:
            state["fired"] = True
            svc.evidence_store.record_intent("racing-key")
            svc.evidence_store.record_terminal(
                EvidenceRecord("racing-key", TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "revocation")
            )
        return real_admit(request, *args, **kwargs)

    setattr(svc.admission_store, _admit_attr, _admit_after_a_revocation_lands)

    with pytest.raises(PermissionError):
        svc.execute(publish)

    assert state["fired"] is True, "the injection point never ran"
    assert adapter.calls == 0, "a revoked epoch must never reach the provider mutation"


# --- (A) shared lock: a revocation cannot land during the admission critical section --
#
# The interleaving pre-seeding a block cannot show (ah#288 CR-3 learned this the hard
# way): here a second thread attempts the revocation WHILE the admission lock is held.
# The admission store calls `self.epoch_blocked()` inside its lock, which is the exact
# in-lock instant; we instrument it to open the window. With a shared lock the writer's
# append MUST block until admit releases. Mutation to kill: give BrokerEvidenceStore its
# own lock file (unshare) -> the writer sails through mid-admission and this fails.

def test_concurrent_revocation_cannot_land_during_the_admission_lock(tmp_path, request):
    adapter = _CountingAdapter()

    activated = fabpub_migrated_activated(
        request,
        symbol=("phase_loop_runtime.convergence.broker.admission", "LinearizableAdmissionStore.admit_next"),
        detail=(
            "the shared-lock proof still exercises legacy admit(); after FABPUB the fresh "
            "publish critical section is admit_next, which must hold the same boundary"
        ),
    )
    if activated:
        from test_convergence_live_enable import _activated_publish_fixture

        _repo, root, publish = _activated_publish_fixture(
            tmp_path, label="race-concurrent", branch="feat/x"
        )
    else:
        root, publish = tmp_path, _pcb_request()
    svc = _service(root, adapter)

    entered = threading.Event()   # set once we are INSIDE the admission lock
    landed = threading.Event()    # set once the revocation write returns
    observed = {}

    def _revoke():
        entered.wait(timeout=5)
        svc.evidence_store.rejected_before_start("racing-key", "concurrent-revocation")
        landed.set()

    writer = threading.Thread(target=_revoke, daemon=True)
    writer.start()

    real_epoch_blocked = svc.admission_store.epoch_blocked

    def _instrumented():
        entered.set()                 # admission lock is held right now
        landed.wait(timeout=0.5)      # give the writer every chance to slip in
        observed["landed_in_window"] = landed.is_set()
        return real_epoch_blocked()

    svc.admission_store.epoch_blocked = _instrumented

    result = svc.execute(publish)
    writer.join(timeout=5)

    assert observed.get("landed_in_window") is False, (
        "a revocation landed while the admission lock was held — the evidence and "
        "admission writers are not sharing one serialization boundary"
    )
    assert result.accepted, "this admission won the lock fairly; it must still publish"
    assert landed.is_set(), "the writer must proceed once the admission releases the lock"
