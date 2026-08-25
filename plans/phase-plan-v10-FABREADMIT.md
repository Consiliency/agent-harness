---
phase_loop_plan_version: 1
phase: FABREADMIT
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - env
    - PHASE_LOOP_TDD_EXPECT_FABREADMIT=1
    - PYTHONPATH=phase-loop-runtime/src
    - python3
    - -m
    - pytest
    - phase-loop-runtime/tests
    - -q
    - -k
    - fabreadmit or readmit or delta_shortcut
    - --junitxml=.phase-loop/runs/fabreadmit-final.junit.xml
---

# FABREADMIT: Broker-Gated Delta Readmission

## Context

FABPUB implementation and its completion ledger are merged and verified on
canonical main. Its activated production route
allocates every publish epoch through one repository-scoped
`LinearizableAdmissionStore`. FABREADMIT consumes that authority: a reviewed
single-commit head advance may become the new admitted head only after the broker
allocates the next epoch, rechecks revocation, and proves the exact prior admitted
head under the same lock. Readmission is admission-only and must never call a
provider adapter.

The maintainer decision in agent-harness#363 is normative: publish and readmission
share one monotonic epoch allocator, and publish byte-neutrality is retracted. The
superseded mechanism in draft PR agent-harness#339 is not an implementation input.
The dormant consumer from agent-harness#191 remains fail-closed until this phase
lands all of agent-harness#288 and flips the engagement interlock.

Current `_fab_delta_readmit` has two direct durable `pr_open` appends: the
already-finalized crash-resume arm and the fresh delta arm. Both bypass broker
authority. This phase routes both through one commit helper and preserves this
ordering:

```text
durable delta provenance and fsync
-> merged FAB gate PASS
-> broker readmission and durable allocated grant
-> durable train-ledger head append
-> in-memory completed-node update
-> exact admitted-head merge
```

The tests-only wave lands first on FABPUB-complete main, is reviewed while RED,
and becomes immutable. Production PRs may not alter its tests, selectors, guard,
or retained RED evidence. All write-capable fanout uses scheduler-owned isolated
worktrees with the disjoint ownership below.

## Interface Freeze Gates

- [ ] IF-0-FABREADMIT-1 - `DeltaReadmitAuthority.v1` is an epoch-free immutable
  request containing canonical repository identity, validated adapter worktree,
  validated train-local checkpoint root, branch/base, exact prior and proposed
  head SHAs, train/node/FAB-run identity, roadmap and provenance-chain digests,
  and the admitted owned-path scope.
  `BrokerClient.readmit_advanced_head(authority) -> DeltaReadmitReceipt` derives a
  deterministic attempt identity and calls the same repository
  `LinearizableAdmissionStore.admit_next` used by publish. The caller cannot
  supply an epoch, attempt ID, fence token, approval digest, or idempotency key.
  Under the admission lock, an additive prior-record predicate proves the exact
  prior head was admitted for the same repository, branch, node, and compatible
  authority; it runs on fresh allocation and deduplicated resume, after current
  revocation/policy checks. An additive `ReadmitAdmissionBinding.v1` on readmit
  admission records carries prior/proposed heads, node, scope, and authority
  digest. The first hop proves node and scope from the exact durable publish
  transaction at that checkpoint root whose recomputed publish idempotency key
  matches the prior admission; later hops prove them from the prior readmit
  binding. A missing, relative, wrong-train, wrong-node, or
  repository-mismatched checkpoint root is denied. The broker independently
  proves `prior..proposed`
  remains within the admitted owned scope. The receipt binds repository, branch,
  prior head, proposed head, allocated epoch, attempt identity, and authority
  digest. No readmission path constructs a provider request or calls an adapter.
  `_commit_broker_readmitted_head` is the only durable readmission head-append
  site and accepts only a matching receipt. `_FAB_DELTA_BROKER_READMIT_READY`
  becomes true only after `FABREADMIT_CAPABILITY_VERSION=1` is active, the
  source-level legacy hardcoded-epoch publisher is retired, and the positive
  end-to-end shortcut proof passes.

## Lane Index & Dependencies

SL-0 — Immutable tests-only contract and RED evidence
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Broker admission-only contract and production router
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes with SL-2

SL-2 — Unified train consumer and durable commit path
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes with SL-1

SL-3 — Activation, documentation, and exact-head evidence reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 - Immutable Tests-Only Contract and RED Evidence

- **Scope**: Freeze every roadmap falsifier, exact interface use, mutation anchor,
  and chronology proof before production code changes.
- **Owned files**: `phase-loop-runtime/tests/_fabreadmit_tdd_guard.py`,
  `phase-loop-runtime/tests/test_fabreadmit_broker.py`,
  `phase-loop-runtime/tests/test_convergence_broker_admission.py`,
  `phase-loop-runtime/tests/test_convergence_broker_verbs.py`,
  `phase-loop-runtime/tests/test_convergence_broker_revocation_race.py`,
  `phase-loop-runtime/tests/test_fab_delta_consumer.py`,
  `phase-loop-runtime/tests/test_fab_activation_promotion.py`,
  `phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py`,
  `phase-loop-runtime/tests/test_train_runner.py`,
  `phase-loop-runtime/tests/test_governed_premerge.py`
- **Interfaces provided**: exact RED node inventory, AST head-append inventory,
  mutation anchors, default-green activation guard, retained JUnit/raw evidence
- **Interfaces consumed**: current FABPUB broker route (pre-existing),
  agent-harness#363 (pre-existing), agent-harness#191 (pre-existing),
  agent-harness#288 (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add a syntax-tree inventory that prints every durable head-carrying
    ledger append and fails if either readmission advance exists outside
    `_commit_broker_readmitted_head`; adding a third site must fail the inventory.
  - test: Add paired fresh controls: an unrevoked real broker readmission allocates
    epoch `N+1`, appends once, and merges; a revocation injected under the lock
    yields zero append, adapter call, or merge.
  - test: Add paired crash-resume controls: crash after broker grant and before
    train-ledger append; unrevoked resume deduplicates the same grant and merges,
    while revocation made durable before resume is rechecked and blocks.
  - test: Reject unrelated, forged, wrong-branch, wrong-node, wrong-scope, or stale
    prior admissions. Make the wrong-node arm non-vacuous for both the first-hop
    durable publish transaction and a chained readmit binding; reject missing,
    relative, wrong-train, wrong-node, and repository-mismatched checkpoint
    roots. Prove linked worktrees and distinct train roots consume the same
    canonical repository allocator.
  - test: Prove the broker independently re-diffs the exact head range, rejects
    owned-scope escape, and performs zero provider-adapter calls.
  - test: Exercise the real repository-routing broker client through `run_train`;
    a direct service fake alone cannot satisfy the positive path.
  - test: Freeze both interlock arms. Any source-level supported publisher that
    still stamps a hardcoded epoch makes enablement fail. Use a source-wide
    syntax-tree inventory with the supported-publisher classification frozen,
    rather than an allow-list of known sites. Once none remains, the production
    predicate is true without monkeypatching the readiness constant and with
    `PHASE_LOOP_TDD_EXPECT_FABREADMIT` absent.
  - test: Add a real-Git end-to-end delta where reviewed-byte equivalence fires,
    broker epoch advances, the train ledger advances, the merged FAB gate passes,
    and merge is pinned to the new admitted head. Run it with the production
    default `resolve_owned_paths=None` and require authority scope to come from
    the durable admitted publish state. Establish the existing FABPUB activation
    barrier and zero-legacy onboarding rather than bypassing the activated store.
    Reverting readiness, injecting a resolver, or bypassing broker readmission
    must kill this test.
  - test: Prefix every new acceptance node with `test_fabreadmit_` so the declared
    automation selector captures the complete retained JUnit evidence.
  - test: Panel the exact tests-only digest using Opus early prover, all Sol/Grok
    4.5/Gemini critics regardless of dissent, then the separate Grok 4.6
    president. Capture the activated RED run on the FABPUB-complete base with
    injection anchors asserted, plus the default-green run with only the exact
    new node inventory skipped.
  - impl: Land the reviewed tests-only PR. Freeze its merge commit and test-tree
    digest. Later lanes must treat all SL-0 files as read-only.
  - verify: `env PHASE_LOOP_TDD_EXPECT_FABREADMIT=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_fabreadmit_broker.py phase-loop-runtime/tests/test_convergence_broker_admission.py phase-loop-runtime/tests/test_convergence_broker_verbs.py phase-loop-runtime/tests/test_convergence_broker_revocation_race.py phase-loop-runtime/tests/test_fab_delta_consumer.py phase-loop-runtime/tests/test_fab_activation_promotion.py phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py phase-loop-runtime/tests/test_train_runner.py phase-loop-runtime/tests/test_governed_premerge.py`

### SL-1 - Broker Admission-Only Contract and Production Router

- **Scope**: Implement IF-0-FABREADMIT-1 inside the repository allocator without
  invoking provider-effect machinery.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py`,
  `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py`,
  `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`,
  `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`
- **Interfaces provided**: IF-0-FABREADMIT-1 authority/receipt surface;
  `DeltaReadmitAuthority`, `DeltaReadmitReceipt`,
  `BrokerClient.readmit_advanced_head`, exact locked prior-record predicate
- **Interfaces consumed**: IF-0-FABREADMIT-1 (pre-existing plan gate), canonical FABPUB repository identity (pre-existing), `LinearizableAdmissionStore.admit_next` (pre-existing)
- **Parallel-safe**: yes, only beside SL-2 in a scheduler-owned worktree
- **Tasks**:
  - test: Consume the frozen SL-0 tests without editing them.
  - impl: Add the epoch-free authority/receipt shapes and deterministic authority
    digest. Keep FAB delta-round epoch entirely outside broker lease allocation.
  - impl: Extend `admit_next` additively so exact prior-record validation occurs
    while the admission lock is held on both fresh and replay paths without
    reordering existing FABPUB policy/precondition gates. Persist the optional
    readmit binding needed to validate chained node/scope authority; match the
    first hop to its durable publish transaction and admission idempotency key
    through the validated checkpoint root.
  - impl: Implement admission-only readmission in `BrokerService` and expose it on
    `_RepositoryRoutingBrokerService`; route by the authority's adapter worktree
    and reject canonical-repository mismatch before store selection.
  - impl: Recompute changed paths and owned-scope coverage inside broker authority.
    Never build `BrokerRequest` for an adapter and never call provider code.
  - verify: `env PHASE_LOOP_TDD_EXPECT_FABREADMIT=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_fabreadmit_broker.py phase-loop-runtime/tests/test_convergence_broker_admission.py phase-loop-runtime/tests/test_convergence_broker_verbs.py phase-loop-runtime/tests/test_convergence_broker_revocation_race.py`

### SL-2 - Unified Train Consumer and Durable Commit Path

- **Scope**: Route fresh and crash-resume readmission through one broker-gated
  train-ledger commit helper.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- **Interfaces provided**: unified readmission commit surface;
  `_commit_broker_readmitted_head`, one durable readmission commit point, and
  production broker-client threading
- **Interfaces consumed**: IF-0-FABREADMIT-1 authority/receipt surface (pre-existing plan gate)
- **Parallel-safe**: yes, only beside SL-1 in a scheduler-owned worktree
- **Tasks**:
  - test: Consume the frozen SL-0 tests without editing them.
  - impl: Build one authority from durable FAB provenance, exact admitted/live
    heads, canonical repository identity, and coordinator runtime, including the
    validated train-local checkpoint root. Load the owned scope from durable
    admitted publish/readmit state; an injected `resolve_owned_paths` result is
    not readmission authority.
  - impl: Make both current direct append arms call
    `_commit_broker_readmitted_head`; require a receipt whose prior/new heads and
    authority digest match before the sole durable append.
  - impl: Preserve fail-closed fallback to `pr-head-advanced`, no-uncaught-escape,
    torn-provenance recovery, exact admitted-head merge pinning, and the existing
    train-ledger `merge_order`/`pr_url` fidelity.
  - impl: Retire `_build_legacy_publish_admission` and any remaining supported
    caller-stamped publish epoch path rather than weakening EC-FABREADMIT-4 to a
    reachability claim.
  - verify: `env PHASE_LOOP_TDD_EXPECT_FABREADMIT=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py phase-loop-runtime/tests/test_train_runner.py`

### SL-3 - Activation, Documentation, and Exact-Head Evidence Reducer

- **Scope**: Enable the consumer only after the integrated mechanism proves every
  negative and positive arm, then reduce exact-head completion evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/fabreadmit_capability.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/publishing.py`, `CHANGELOG.md`
- **Interfaces provided**: active production delta shortcut and closeable evidence
  for agent-harness#191 and agent-harness#288
- **Interfaces consumed**: exact RED node inventory (from SL-0), unified readmission commit surface (from SL-2), IF-0-FABREADMIT-1 authority/receipt surface (from SL-1), exact merged FABPUB capability marker (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Consume the frozen SL-0 tests without editing them.
  - impl: Add `FABREADMIT_CAPABILITY_VERSION=1` using the sibling FABPUB
    marker/test-environment convention. Replace the readiness constant with an
    enablement check that is true only for this completed broker-readmission
    capability, active FABPUB capability, and absence of hardcoded-epoch
    publishers. `PHASE_LOOP_TDD_EXPECT_FABREADMIT=1` may activate only the new
    capability-marker conjunct; it may not short-circuit active FABPUB or the
    hardcoded-epoch absence check. Keep both operator/coordinator opt-ins
    mandatory.
  - impl: Preserve transaction construction for a reviewed branch that does not
    yet have a local ref by resolving the named branch and then `HEAD` after the
    canonical `refs/heads/<branch>` lookup. This is required by the frozen
    first-hop key-mismatch falsifier so broker validation, rather than an
    unrelated missing-ref error, remains the observed boundary.
  - impl: Update the CHANGELOG with broker-gated readmission, active reviewed-byte
    shortcut, zero provider effect during readmission, and the already-ratified
    publish byte-neutrality retraction.
  - verify: Run the exact end-to-end positive case and all fresh/resume revocation,
    prior-poisoning, flag-reversion, owned-scope, router, inventory, and no-adapter
    mutations. Record JUnit, invocation, source-tree digest, and exact commit.
  - verify: Run the ordered exact-head implementation board and separate Grok 4.6
    president. Every deferred finding must be filed verbatim before dispatch.
  - verify: After merge, rerun the same suite on exact main before marking
    agent-harness#191 or agent-harness#288 closeable.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`block`, inherit-default=`false`
- plan: executor=`codex`, model=`gpt-5.6-sol`, effort=`xhigh`, work-unit=`phase_plan`, reason=`maintainer-selected planning authority`
- SL-0: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`lane_execute`, reason=`FABREADMIT single-author-vendor tests-first lane`
- SL-1: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`lane_execute`, reason=`FABREADMIT single-author-vendor broker lane`
- SL-2: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`lane_execute`, reason=`FABREADMIT single-author-vendor consumer lane`
- SL-3: executor=`gemini`, model=`gemini-3.6-flash`, effort=`high`, work-unit=`lane_execute`, reason=`FABREADMIT single-author-vendor activation lane`
- review: executor=`codex`, model=`gpt-5.6-sol`, effort=`xhigh`, work-unit=`lane_review`, reason=`ordered board coordination`

## Execution Notes

- Hand-enforce agent-harness#441 and agent-harness#442 at every gate until
  REVIEWTRUTH implements them: Opus early prover first; Sol, Grok 4.5, and Gemini
  critics all run regardless of dissent; then a separate Grok 4.6 president pass.
- The president rules each finding `BLOCKING` or `DEFERRED`, is bound to exact
  finding text and artifact digest, cannot rule on its own findings, and has at
  most three rounds. A deferred finding must have a filed issue before dispatch.
- A finding contradicting retained RED evidence, exact attestation, or a frozen
  test invariant is not deferrable.
- Gemini is the single author vendor for the whole phase, preserving independent
  closeout reviewers; SL-1 and SL-2 may run concurrently only through
  same-vendor workers after the scheduler verifies disjoint owned files and
  assigns separate worktrees. SL-3 is always serial. The next code-writing phase
  rotates to a different author vendor.
- FABREADMIT may run beside HARDEN until either phase reaches its `CHANGELOG.md`
  writer; those documentation lanes serialize because both own that file. Both
  phases rerun their exact selector after the other lands. SCHED lane B remains
  ordered before HARDEN as specified by the roadmap.
- No release, tag, package publication, or production pilot occurs in this phase.

## Verification

```bash
env PHASE_LOOP_TDD_EXPECT_FABREADMIT=1 \
  PYTHONPATH=phase-loop-runtime/src \
  python3 -m pytest -q \
  phase-loop-runtime/tests/test_fabreadmit_broker.py \
  phase-loop-runtime/tests/test_convergence_broker_admission.py \
  phase-loop-runtime/tests/test_convergence_broker_verbs.py \
  phase-loop-runtime/tests/test_convergence_broker_revocation_race.py \
  phase-loop-runtime/tests/test_fab_delta_consumer.py \
  phase-loop-runtime/tests/test_fab_activation_promotion.py \
  phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py \
  phase-loop-runtime/tests/test_train_runner.py \
  phase-loop-runtime/tests/test_governed_premerge.py

PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q \
  phase-loop-runtime/tests -k "broker or admission or convergence or fab"

PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q \
  phase-loop-runtime/tests -m "not dotfiles_integration"

ruff check phase-loop-runtime/src/phase_loop_runtime/
git diff --check
```

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none outside this repository
- evidence paths: `.phase-loop/evidence/FABREADMIT/spec-delta-closeout.json`, `.phase-loop/evidence/FABREADMIT/issue-dispositions.json`
- redaction posture: `metadata_only`
- malformed evidence disposition: non-human `contract_bug`
- closeout evidence: exact tests-only merge and immutable test-tree digests,
  activated RED/default-green receipts, implementation and activation landings,
  exact-main JUnit/invocation/source digests, ordered board artifacts, and issue
  dispositions for agent-harness#191, agent-harness#288, agent-harness#339, and
  agent-harness#363; the closeout records the necessary key-file widening from
  the roadmap's three-file summary to the plan's broker and capability surfaces,
  plus the run-local operator substitution of Opus early prover and Grok 4.6
  president for the superseded Fable topology

## Acceptance Criteria

- [ ] EC-FABREADMIT-0 — proven by `git diff --exit-code <tests-only-merge>...HEAD -- <SL-0-owned-files>` plus the exact RED/default-green receipt reducer; falsified by an implementation commit predating the tests-only commit, an implementation diff touching an SL-0-owned file, or a retained RED receipt whose injection anchor was not asserted; path-entered control: the activated RED run reaches every recorded injection anchor while the default run remains green.
- [ ] EC-FABREADMIT-1 — proven by `pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py -k "commit_points or append_site_inventory"`; falsified by restoring either direct durable head append and observing the inventory or behavioral test accept it; path-entered control: the fresh and resume controls both reach `_commit_broker_readmitted_head`.
- [ ] EC-FABREADMIT-2 — proven by `pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py -k "fresh_revocation"`; falsified by removing the fresh-path revocation check and observing a revoked delta merge; path-entered control: an unrevoked delta on the same path reaches broker readmission and merges.
- [ ] EC-FABREADMIT-3 — proven by `pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py -k "crash_resume_revocation"`; falsified by removing the crash-resume revocation recheck and observing the early append complete after revocation; path-entered control: an unrevoked crash-resume reaches the same append and merges.
- [ ] EC-FABREADMIT-4 — proven by `pytest -q phase-loop-runtime/tests/test_fab_activation_promotion.py -k "hardcoded_epoch or interlock"`; falsified by retaining a supported publisher that stamps a hardcoded epoch and observing the readiness interlock enable; path-entered control: retiring all such publishers permits the production capability check to become true.
- [ ] EC-FABREADMIT-5 — proven by `pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py -k "append_site_inventory_detects_third_site"`; falsified by adding a third head-advancing append and observing the syntax-tree inventory miss it; path-entered control: the inventory visits and reports the unified authorized append site.
- [ ] EC-FABREADMIT-6 — proven by `pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py phase-loop-runtime/tests/test_fab_activation_promotion.py -k "real_git_shortcut or flag_reversal"`; falsified by reverting readiness and observing the real-Git shortcut test continue to pass; path-entered control: the positive case records the shortcut firing, broker epoch advancing, ledger advancing, and exact-head merge.
- [ ] EC-FABREADMIT-7 — proven by `pytest -q phase-loop-runtime/tests/test_fab_delta_consumer.py phase-loop-runtime/tests/test_fab_activation_promotion.py -k "real_git_shortcut"` on exact main plus the issue-closeout reducer for agent-harness#191; falsified by marking agent-harness#191 closeable while the real-delta shortcut remains dormant or unthreaded; path-entered control: exact-main evidence records the shortcut firing on a real delta.
