---
phase_loop_plan_version: 1
automation:
  suite_command:
    - env
    - PHASE_LOOP_TDD_EXPECT_FABPUB=1
    - PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
    - python3
    - -m
    - pytest
    - -q
    - phase-loop-runtime/tests/test_publisher_effect_fence_820.py
    - phase-loop-runtime/tests/test_convergence_broker_credsep.py
    - phase-loop-runtime/tests/test_pr_readback_789.py
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a0_derivation_sites_match_the_plan_allow_list
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a17_flip_fences_pre_flip_lease_and_fresh_writers
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a26_concurrent_writer_lands_before_digest_or_is_fenced
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py::test_fabpub_shared_adapter_start_fence_blocks_competing_train_before_and_after_possible_provider_effect
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py::test_fabpub_legacy_writer_quiescence_blocks_armed_activation_and_fences_supported_restarts
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py::test_fabpub_post_activation_writer_generation_fence_blocks_direct_and_old_cli_restarts
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a17e_authorized_before_flip_is_refused_in_lock
    - --junitxml=.phase-loop/diagnostics/effect-fence-820/junit.xml
---

# Detailed plan: fence each synchronous publisher effect against generation changes

Status: DRAFT, awaiting the required exact-artifact four-seat review. Default mode
planning only; no runtime implementation or production recovery is approved by
this artifact. Issue: Consiliency/agent-harness#820. Input base:
`88833fff1cce8ab1076f3be8a1596d875ddb5f20`.

## Task

Close the demonstrated check/use gap between generation validation and each
synchronous GitHub mutation. This is the first bounded repair toward publication
recovery. It does not implement a V10 exit criterion or complete agent-harness#820.
Keep this repair separate from agent-harness#734, HARDEN and the protected primary.
The guarantee covers resolved namespaces with valid leases. The existing broad
namespace-resolution compatibility bypass is separately tracked as agent-harness#833;
this slice does not establish safe admission for that path or authorize deployment.

## Research summary

`convergence/broker/credsep.py::GitHubBrokerAdapter.execute` validates the generation,
releases the latch lock, then calls `git push`. Its later `gh pr create` has no
generation check. The archived scratch probe pauses at the push boundary, releases
the lease, enters DRAINING, and then reaches both fake mutations. No actual provider
command ran. Evidence: `agent-harness#820` comment `5627970722` and
`/mnt/workspace/archives/agent-harness-820-investigation-20260911-012457/diagnostics/effect-gap-results.json`.
That investigation's partial panel is not approval of this plan.

`live.py::WriterGenerationLatch.exclusive`, `validate_lease`, `release` and
`begin_draining` already share one repository-common lock. `verbs.py::_fresh_publish`
calls the adapter outside `admissions.lock`; terminal recording follows its return.
Rotation takes `admissions.lock` before the latch. Consequently the new provider
section may validate and execute the subprocess, but must not acquire a store lock,
append evidence, release a lease, or wait for drain while holding the latch.
On this base, active-root validation calls layout helpers and filesystem pointer
reads; those helpers acquire no store lock. Preserve validation-only lock duration.

The unchanged A0 derivation sweep inventories namespace derivations by enclosing
function. Keep derivation and validation in the existing
`require_current_generation`; adding a second derivation helper would require
a different frozen inventory. Include A0 in verification, with its allow-list
and sweep unchanged. Do not rename parameters or move tokens to evade that check.

Preserve the protocol at `live.py:545-553`, including the exact existing line:
`GENERATION_STATES = ("LEGACY_OPEN", "DRAINING", "ACTIVE")`.
No new persisted state, lease schema, terminal vocabulary or authority format is
introduced. Preserve `outcome_ambiguous_blocked` permanence and the current rule
allowing acquisition of the canonical generation while DRAINING; changing that
rule belongs to separately reviewed recovery admission work.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py` (modify)

- Extend the existing `require_current_generation` with an optional keyword-only
  synchronous `effect` callback. Without a callback, retain validation-only calls
  and their `None` result and existing lock duration. Only callback calls with an
  existing latch hold an outer `exclusive()` section
  while performing the existing complete generation/lease/active-store validation
  and then invoking the callback exactly once. Return the callback's result and
  propagate its exception after unwinding the lock. Reuse `validate_lease` through
  the existing reentrant section; do not duplicate validation or derivation.
- Preserve missing-latch plus authenticated-receipt refusal. In the existing
  missing-latch/no-authority compatibility branch, invoke/return a supplied
  callback without creating a latch or lease. That branch provides no generation
  fence; do not claim the activated guarantee for it.
- Do not change `acquire`, `release`, drain/rotation transitions, lease JSON or the
  reentrant-lock primitive. No generic process reaper or recovery command is added.

### `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py` (modify)

- Extend `_revalidate_generation_before_effect` with the same optional `effect`
  callback and return its result through `require_current_generation`. Keep all
  existing namespace resolution in this method. Preserve strict refusal after
  successful resolution when authority is absent or undeclared. The existing
  capability-off and undeclared namespace-resolution exception branches invoke
  a supplied callback once; validation-only calls still return `None`. Do not
  describe the latter as proven synthetic: agent-harness#833 reproduces it in a
  real repository with malformed routing. Its admission repair is separate and
  remains a prerequisite for claiming safe publication recovery.
- Route both `git push` and `gh pr create` through that method, separately, each
  using a callback containing only its existing synchronous `self.run` call.
  The callbacks never write broker evidence, acquire `admissions.lock`, release
  leases, retry a provider request, or change argv/environment. Keep
  local probes and remote read-back outside it. Recovery may run between the two
  calls: a subsequent PR-create must then be fenced. Keep exact origin, commit,
  base, owned-path, draft, existing-PR and remote-readback behavior unchanged.
- Preserve the existing failure path: refusal after a possible push is not a
  no-effect result. If DRAINING also prevents recording a terminal, retain the
  in-flight evidence and unsealed owner; do not fabricate a terminal or seal.

### `phase-loop-runtime/tests/test_publisher_effect_fence_820.py` (create)

- Import existing scratch fixtures from `test_convergence_broker_credsep` and
  FABPUB fixtures from their owning test modules. All namespaces, authorities and
  providers are temporary/fake. Never use the live repository authority.
- Assert FABPUB activation inside the new module. Use Events/Pipes with bounded
  watchdogs and an independent spawned or exec'd process
  to contend for the real lock. Reproduce the original unlocked gap before the
  repair. A spy asserting that a helper was called is insufficient.
  Do not fork a contender while the owner holds the latch: it would inherit
  the lock description and reentrancy bookkeeping. Separate-open thread controls
  may supplement the required process control.
- Cover push and PR-create separately: while the synchronous call is paused,
  actual release/drain cannot complete; after it returns, they can. A nonblocking
  independent lock probe must fail during the section and succeed afterward.
- Pause between push and PR-create, enter DRAINING, then resume: push count is one,
  PR-create count is zero, and the operation cannot report accepted/no-effect or
  a sealed owner. Assert retained ambiguous or in-flight evidence through the
  actual BrokerService path, including a failed terminal append under DRAINING.
  Permit that append's exception to propagate and inspect the durable record;
  no result object is guaranteed. Cover both an explicitly supplied lease held
  across terminal recording and a service-acquired temporary lease.
- Cover stale/missing leases, provider exception unwinding, normal successful
  push/create/readback, linked worktrees sharing the gate, and unrelated
  repositories retaining independent gates. Check the actual lock order using
  concurrent recovery and terminal recording with bounded completion.
- Cover validation-only calls, exact callback result/exception propagation, and
  capability-off/synthetic/missing-latch compatibility. Refuse a missing latch
  with an authenticated receipt. Confirm that permitted compatibility creates
  no latch/lease and makes no claim to activated-generation exclusion.
- Mutate away the held section and independently remove the PR-create guard;
  the corresponding tests must fail at the intended behavior, not at import or
  collection. Preserve all existing/frozen test files and guards byte-for-byte.

### `docs/fabpub-partition-rotation-runbook.md` (modify)

- Document the bounded synchronous guarantee and update the residual-effects
  discussion to distinguish store fencing from provider-effect fencing.
- The existing push/create calls have no timeout. This slice deliberately holds
  the namespace latch for their full synchronous duration: a hung call can block
  same-namespace appends, lease operations and rotation indefinitely. Do not add
  a timeout/kill policy in this slice or present it as operational recovery.
  Separate sections preserve a generation check immediately before each effect;
  a drain between them may leave a pushed branch without a new PR.
- Preserve the live recovery prerequisites. Explicitly record that a parent
  process dying may leave a provider child alive after its lock disappears;
  neither this fix nor a zero-result process scan establishes orphan ownership.
  The September 10 boot and unchanged lease timestamps do not rule out adoption
  of persisted v1 handles by a newer process. Do not add operational deletion,
  rotation, risk-acceptance, or reboot instructions in this repair.
  Python's non-inheritable descriptor closes at child exec; a fork-only descendant
  can retain it. Parent death alone therefore proves neither effect cancellation
  nor lock release. Preserve conservative ambiguous classification even for a
  fence refusal before the first effect; typed no-effect refinement is separate.

## Dependencies and order

1. Complete the required native four-seat review of these exact plan bytes under
   the current agent-harness#752 policy. Fable's September 12 01:18 UTC native
   availability check passed, but is not a review vote. Preserve the earlier
   quota evidence and do not substitute the previously refused Opus request.
2. Reconcile live source/ownership and agent-harness#789's separately pending
   `credsep.py` repair before implementation. Preserve its changes; a changed
   implementation base requires fresh evidence and exact candidate review.
3. Implement the new tests, retain the meaningful RED result, then make the two
   source edits and document the limit. Run the bounded verification below and
   the two targeted mutation controls. Do not rerun the full HARDEN suite.
   Before edits, inspect the selected frozen tests for old-signature fakes,
   exact call counts and blocking runner interactions. Include those exact
   contexts in the plan review. Importable private fixture names need no edits
   to their modules. A new-keyword TypeError alone is not meaningful RED: the
   original exclusion/second-effect witnesses must fail on behavior.
4. Complete exact-candidate native review and the normal publication-owner gates.
   This repair creates no route around the current permanent ambiguity.
5. Only after this slice is reviewed, design the distinct child-lifetime and
   recovery-admission contract. It must cover parent death, fork/exec/detached
   descendants, guaranteed close, and preventing new starts during recovery.
   Then separately establish legacy-v1 migration/shutdown proof. A new runtime
   cannot retroactively constrain already loaded old code. Those follow-ups
   are intentionally not specified prematurely by this bounded plan.

## Verification and acceptance criteria

Run the `automation.suite_command` above in the isolated implementation worktree
with the repository's supported Python environment, after composing the pending
agent-harness#789 dependency. Its unchanged `test_pr_readback_789.py` is a required
RED/GREEN gate on that composed candidate, not only a dependency baseline.
Bind each invocation to the actual base and candidate file hashes. Collect JUnit and exact
source/fixture hashes. A selected frozen test that skips is not acceptance.
The new module must have no skip-based escape from the synchronous-fence tests.
Use the same command for RED/GREEN; run mutation controls only against isolated
temporary copies and retain their failing node IDs.

The added shared-epoch quiescence node pins validation-only DRAINING refusal;
the post-activation node pins strict missing-lease admission/evidence refusal,
both direct adapter refusal forms, and a current-generation positive control.
A17e pauses after writer prechecks and before store-lock acquisition, proving
the existing append-time check/use contract. These existing files stay frozen.
The new module supplies the direct missing-latch/authenticated-receipt and
validation-only return/lifetime controls; no existing node is claimed to prove
those exact helper behaviors. Before each invocation, preserve any prior
`junit.xml` and command log under its RED/GREEN or mutation evidence label, verify
their hashes, then run the identical suite command. Never overwrite the sole
copy of a previous result. The lockfile test group supplies the supported pytest.

- [ ] The new module proves release/drain exclusion over both synchronous
      mutations; removing the held section fails the intended test.
- [ ] The new module proves drain between push and create fences the latter;
      removing only that second guard fails the intended test.
- [ ] The new module proves exception cleanup, strict stale/missing authority,
      shared-worktree exclusion, repository isolation and safe lock ordering.
- [ ] The new module plus unchanged credential-boundary tests prove the normal
      exact-head publish/readback path and preserved partial-effect ambiguity.
- [ ] All named existing nodes in the suite remain passing, with their test and
      guard hashes unchanged. Source changes are confined to the two listed
      implementation modules and are bound to fresh candidate evidence.
- [ ] `git diff --check` passes; a scope/hash audit records only the four listed
      implementation files and the separate plan/manifest/review artifacts.
- [ ] Native reviews bind the final plan and implementation artifacts, and the
      handoff explicitly leaves agent-harness#820, legacy lease cleanup,
      publication ambiguity and downstream V10 acceptance unresolved.

No implementation source changed while writing this plan. Isolated follow-up
probes confirmed local flock exclusion and the agent-harness#833 pre-check bypass;
they are input evidence, not a GREEN result for this future repair. Retain the
three partial verdicts on the previous draft; they do not approve these bytes.
