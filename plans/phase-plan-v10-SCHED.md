---
phase_loop_plan_version: 1
phase: SCHED
roadmap: specs/phase-plans-v10.md
roadmap_sha256: c66949236043e46e956caec1c09d0c19d0e8751e4ce2891de1fe2edf24e9fea1
automation:
  suite_command: 'PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py phase-loop-runtime/tests/test_phase_loop_runner.py'
---

# SCHED: Scheduler and Worktree Reclamation

## Context

SCHED closes the scheduler-dispatch and crash-residual worktree defects carried by
`Consiliency/agent-harness#300`, `Consiliency/agent-harness#301`,
`Consiliency/agent-harness#353`, and draft `Consiliency/agent-harness#354`.
The active roadmap requires SCHED after completed PROOFGATE and before REVIEWTRUTH.
At this plan's base, PROOFGATE is completed, while SCHED has no manifest row or
execution-ready plan. Draft `Consiliency/agent-harness#354` is not an implementation
base: review proved that its same-phase recreation force-deletes recoverable work,
ignored handoffs are durable state, and a path-based age/status check has a deletion
TOCTOU. Its block/reuse/transfer proposals also lacked an active-owner exclusion and
treated closeout handoffs as session checkpoints.

The ratifiable third framing is a leased, generation-addressed lifecycle. The parent
holds an exclusive lifetime lease for every active phase worktree. A crashed parent
releases that lease at the kernel boundary. Reclamation may acquire the released lease
only non-blockingly and may delete only a fully authenticated, stable candidate with no
tracked, untracked, ignored, committed, or handoff state. Any uncertainty preserves the
candidate and its branch. Creation never force-removes a preserved generation: it mints
a fresh generation-specific path and branch, and the scheduler consumes the returned
assignment instead of recomputing a deterministic pathname. This is not resume-first;
preserved bytes remain evidence/recovery material and are never interpreted as a
checkpoint.

The phase has two production writers, matching the roadmap: worktree reclamation and
the scheduler cluster. Control lanes enforce a separately merged decision record, a
separately merged tests-only RED boundary, and a post-implementation evidence/docs
reducer. All SL-1 tests are immutable after their tests-only landing. Production PRs may
not modify them.

## Interface Freeze Gates

- [ ] IF-0-SCHED-1 — `PhaseWorktreeHandle` carries the exact generation, path,
  temporary branch, target branch, base SHA, and active lease authority returned by
  creation; callers never reconstruct an active path from phase/branch strings.
- [ ] IF-0-SCHED-2 — worktree cleanup is preserve-by-default and requires an acquired
  inactive lease plus two stable inventories proving no tracked, untracked, ignored,
  committed, handoff, or special-file state before removal. Errors, drift, and live
  leases preserve.
- [ ] IF-0-SCHED-3 — an occupied deterministic generation never triggers `--force`
  removal. Creation selects a collision-resistant generation-specific path/branch and
  returns it to every phase/lane assignment consumer.
- [ ] IF-0-SCHED-4 — plan-declared `execution_policy.work_unit_kind` is authoritative
  at both scheduler selection sites; text heuristics are compatibility fallback only
  when the plan declares no supported kind.
- [ ] IF-0-SCHED-5 — concurrent planning artifacts and blocked work remain recoverable:
  dirty child output reaches the parent only through ownership-gated transport under a
  committing closeout, while manual/failed closeout preserves the child branch. No-diff
  work skips artifact-dependent phase verification without skipping verification for a
  real diff.
- [ ] IF-0-SCHED-6 — the SCHED disposition records the two surviving historical branch
  tips and the accepted possible loss from the removed `phase/abdresolve` worktree
  without claiming that unknown work was recovered.

## Lane Index & Dependencies

SL-0 — Ratify leased generational recovery
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no

SL-1 — Immutable tests-only RED boundary
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Worktree lease, generation, and conservative reclamation
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Scheduler kind, artifact transport, and no-diff dispatch
  Depends on: SL-1, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — Documentation, disposition, and completion evidence
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Delivery Boundaries

1. The planning package carries an exact-digest native-first board review artifact.
2. The SL-0 closeout records a record-only changed-path set and the reviewed canonical
   main ancestry before test authorship begins.
3. The SL-1 closeout records a tests-only changed-path set and panelled RED evidence.
   Its test paths are immutable for SL-2 through SL-4.
4. The SL-2 and SL-3 closeouts record production-only changed-path sets in dependency
   order. Neither closeout may contain an SL-1 path.
5. The SL-4 closeout records exact-main replay of every roadmap criterion and retained
   historical disposition.

## Lanes

### SL-0 — Ratify leased generational recovery

- **Scope**: Record the maintainer-approved third framing and reject destructive,
  resume-first, and handoff-as-checkpoint interpretations before tests or runtime edits.
- **Owned files**: `docs/research/sched-worktree-recovery-ratification.md`
- **Interfaces provided**: `SCHED_RECOVERY_DECISION`.
- **Interfaces consumed**: active roadmap and current worktree lifecycle source
  (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: mechanically verify the record names lease ownership, complete ignored-state
    preservation, generation-specific replacement, no checkpoint inference, and the
    historical branch/loss disposition.
  - impl: write only the decision record; cite the exact reviewed main and the complete
    rejected design set.
  - verify: require a clean record-only diff and an ancestry receipt binding the reviewed
    head to the fetched pre-landing canonical main tip.

### SL-1 — Immutable tests-only RED boundary

- **Scope**: Freeze every roadmap falsifier and positive control against the post-SL-0,
  pre-production base, then land those tests separately.
- **Owned files**: `phase-loop-runtime/tests/test_phase_worktree_executor.py`,
  `phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py`,
  `phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py`,
  `phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py`,
  `phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py`,
  `phase-loop-runtime/tests/test_phase_loop_runner.py`
- **Interfaces provided**: `SCHED_RED_SUITE`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`.
- **Parallel-safe**: no.
- **Tasks**:
  - test: add falsifiers for same-phase committed work, dirty/untracked state, an ignored
    `.dev-skills/handoffs/`-only candidate, a held live lease, post-scan mutation, lease
    identity drift, and generation/path/branch collision. Assert that each preserves the
    old generation and its ref.
  - test: add a positive control proving a released-lease candidate with an exact empty
    inventory can be reclaimed and a fresh generation can launch.
  - test: add production-path tests proving declared `lane_execute` overrides a Verify-body
    reducer heuristic at both sites; nested dispatch carries one run identity; a staged
    planner artifact survives concurrent parent reduction; manual/blocked closeout retains
    the child ref; no-diff skips only artifact-dependent verification; a real diff still
    verifies.
  - test: run every mutation against the exact pre-production base, require the injection
    anchor to execute, record expected RED, restore the source, and record unchanged
    positive controls.
  - verify: run the six owned modules plus Ruff and `git diff --check`; require the new
    falsifiers RED for the intended reason and all unrelated existing tests green.

### SL-2 — Worktree lease, generation, and conservative reclamation

- **Scope**: Implement the ratified lifetime lease and generation-addressed,
  preserve-by-default worktree lifecycle without interpreting handoffs as checkpoints.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`,
  `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`
- **Interfaces provided**: `SCHED_WORKTREE_AUTHORITY`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`, `SCHED_RED_SUITE`, and existing
  Git worktree index and transport primitives (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - impl: acquire and retain a kernel lifetime lease before exposing an active handle;
    release it only after teardown or parent failure cleanup. Do not rely on PID, mtime,
    directory age, or handoff presence as liveness authority.
  - impl: enumerate tracked, untracked, ignored, committed, symlink, and special-file
    state without following links; compare stable pre/post identities and fail closed on
    unreadable or changing paths.
  - impl: preserve every candidate carrying any recoverable state. Reclaim only a proven
    inactive, empty generation and revalidate immediately before removal; never use
    `--force` as a substitute for the lease/inventory proof.
  - impl: when the canonical generation is occupied or preserved, mint a collision-resistant
    path and temporary branch and return those exact values. Preserve all older branches.
  - verify: make the SL-1 worktree tests green without changing them; run all existing
    phase-worktree and worktree-index regressions.

### SL-3 — Scheduler kind, artifact transport, and no-diff dispatch

- **Scope**: Make both schedulers consume returned worktree authority, honor declared
  work-unit kind, preserve child artifacts, and avoid artifact-dependent verification on
  an exact no-diff result.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_scheduler.py`,
  `phase-loop-runtime/src/phase_loop_runtime/runner.py`,
  `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`
- **Interfaces provided**: `SCHED_RUNTIME`.
- **Interfaces consumed**: `SCHED_WORKTREE_AUTHORITY`, `SCHED_RED_SUITE`, and existing
  DispatchLock `caller_run_id` support and ownership-gated closeout (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - impl: prefer a valid declared `lane_execute`/`phase_reducer` kind at both scheduler
    sites, retaining the current heuristics only for undeclared legacy plans.
  - impl: thread one local run identity through `DispatchLock` and child executor env
    without mutating process-global environment; genuine competing runs retain normal
    contention.
  - impl: propagate actual generation/path assignments returned by creation. Eliminate
    recomputation of a live assignment from branch/lane strings.
  - impl: transport staged/dirty planning output before parent reduction only under
    commit/push closeout; on manual closeout, transport conflict, block, or failed adoption,
    preserve the child branch and emit a recoverable typed event.
  - impl: skip artifact-dependent phase verification only after a production result proves
    an exact no-diff; retain normal verification for any real diff or ambiguous result.
  - verify: make the SL-1 scheduler tests green without changing them; run lane scheduler,
    concurrent dispatch, work-unit, dispatch-lock, and runner suites.

### SL-4 — Documentation, disposition, and completion evidence

- **Scope**: Reconcile public scheduler documentation and reduce exact-main evidence after
  both implementation landings.
- **Owned files**: `CHANGELOG.md`, `docs/research/sched-worktree-reclamation-evidence.md`
- **Interfaces provided**: `SCHED_COMPLETION_EVIDENCE`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`, `SCHED_RED_SUITE`,
  `SCHED_WORKTREE_AUTHORITY`, `SCHED_RUNTIME`, and exact merged commits (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - impl: document lease-backed generation behavior, preserve-by-default recovery, and
    the no-checkpoint boundary; describe declared-kind and planner-artifact behavior.
  - impl: record the two surviving historical branch tips from fresh canonical remote
    metadata and retain the `phase/abdresolve` unknown-loss finding as unmet historical
    state, never as recovered work.
  - verify: run the full phase suite on exact canonical main, validate Git ancestry and
    all changed-path boundaries, then produce metadata-only verification evidence.

## Verification

Run from the repository root unless stated otherwise.

```bash
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests/test_phase_worktree_executor.py \
  phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py \
  phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py \
  phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py \
  phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py \
  phase-loop-runtime/tests/test_phase_loop_runner.py
```

```bash
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests/test_phase_loop_worktrees.py \
  phase-loop-runtime/tests/test_worktree_index.py \
  phase-loop-runtime/tests/test_dispatch_lock_same_roadmap.py \
  phase-loop-runtime/tests/test_dispatch_lock_cross_roadmap.py \
  phase-loop-runtime/tests/test_dispatch_lock_helper.py
```

```bash
cd phase-loop-runtime
uv run --locked ruff check .
uv lock --check
python3 scripts/check_model_id_sources.py
git diff --check
```

The final exact-main gate is:

```bash
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  -m "not dotfiles_integration"
```

## Execution Notes

- SL-0, SL-1, SL-2, and SL-3 produce distinct review-boundary receipts. The coordinator
  records each canonical target tip, reviewed head, resulting ancestry, and exact
  changed-path set before advancing.
- The SL-1 RED evidence uses `verification_evidence.v3`. Each mutation record carries
  the exact nodeid, source anchor, mutation digest, expected failure anchor, restored
  source digest, and positive-control result. A missing or non-biting mutation blocks.
- The implementation may not change any SL-1 owned file. A test correction requires a
  new separately reviewed tests-only successor before further production edits.
- The final reducer replays the exact merged bytes from canonical main; branch-local
  evidence, self-authored summaries, or a stale worktree cannot complete SCHED.

## Acceptance Criteria

- [ ] EC-SCHED-0 — proven by `git diff --name-only "$SCHED_SL1_BASE..$SCHED_SL1_LANDING"`
  equaling the six SL-1 paths, `git merge-base --is-ancestor "$SCHED_SL1_LANDING"
  "$SCHED_IMPLEMENTATION_LANDING^1"`, and the `verification_evidence.v3` reducer.
  Falsified by a path-entered control showing an implementation ancestor preceding the
  tests landing, a non-biting RED mutation, or any SL-1 path in an implementation diff.
- [ ] EC-SCHED-1 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py -k
  create_preserves_recoverable_generation`; falsified by a path-entered mutation restoring
  unconditional force removal and observing the preserved generation disappear.
- [ ] EC-SCHED-2 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py -k
  recovery_ratification`; falsified by a path-entered control where the old
  stale-worktree test still asserts disappearance or the decision record does not select
  the ratified mechanism.
- [ ] EC-SCHED-3 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py -k
  ignored_handoff_only`; falsified by a path-entered classification mutation that treats
  the ignored handoff as empty and reaches removal.
- [ ] EC-SCHED-4 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py -k
  declared_lane_execute`; falsified by a path-entered mutation restoring the Verify-body
  heuristic at either scheduler site and observing `phase_reducer`.
- [ ] EC-SCHED-5 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py
  -k staged_plan`; falsified by a path-entered committed-only reduction that removes or
  overwrites the validated planner artifact while the positive reduction control runs.
- [ ] EC-SCHED-6 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py
  -k 'no_diff or real_diff'`; falsified by a path-entered no-diff result reaching
  artifact-dependent verification or by a real diff bypassing verification.
- [ ] EC-SCHED-7 — proven by `git ls-remote origin refs/heads/feat/advisor-board-abdreg
  refs/heads/phase/abdresolve` and exact identities recorded in
  `docs/research/sched-worktree-reclamation-evidence.md`; falsified by either remote ref
  disappearing without a recorded decision or by the reducer claiming the unknown
  `phase/abdresolve` bytes were recovered.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `docs/research/sched-worktree-recovery-ratification.md`,
  `docs/research/sched-worktree-reclamation-evidence.md`
- evidence paths: `plans/phase-plan-v10-SCHED.md`,
  `docs/research/sched-worktree-reclamation-evidence.md`
- redaction posture: `metadata_only`
- downstream handling: none
