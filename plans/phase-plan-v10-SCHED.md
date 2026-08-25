---
phase_loop_plan_version: 1
phase: SCHED
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command: 'PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py phase-loop-runtime/tests/test_phase_loop_runner.py phase-loop-runtime/tests/test_phase_loop_launcher.py phase-loop-runtime/tests/test_workerpool_failure_isolation.py phase-loop-runtime/tests/test_workerpool_parallel.py phase-loop-runtime/tests/test_workerpool_worktree_alloc.py phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py phase-loop-runtime/tests/test_phase_loop_v45_sched.py phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py'
---

# SCHED: Scheduler and Worktree Reclamation

## Context

The roadmap objective and seven interface gates remain unchanged. The accepted SL-0
ratification record is the design authority. The exact rejected tests-only head named in
the board bundle did not land; all six finding clusters were blocking. SL-1 therefore
means a separately reviewed tests-only successor on a recorded pre-production base;
SL-2 and SL-4 may not start until that successor lands. Its tests become immutable only
after acceptance.

One implementation vendor owns the successor and both production lanes; review boards
do not author implementation. SL-2 and SL-4 remain disjoint and may run concurrently
after SL-1. No future commit, PR, tag, commit count, or topology is prescribed.

## Interface Freeze Gates

- [ ] IF-0-SCHED-1 — `PhaseWorktreeHandle` returns generation, exact path and branch,
  target, base SHA, and typed live lease authority. Runner and worker records pass that
  capability to `launch_with_spec`/`launch`; the launcher supervisor inherits it with
  POSIX `pass_fds`, creates the executor session, becomes a subreaper, and retains it
  until every descendant is reaped. It is never serialized or reconstructed by path.
- [ ] IF-0-SCHED-2 — cleanup preserves by default. Owner teardown holds the original
  lease through authenticated empty-inventory removal; crash reclamation nonblockingly
  acquires a released lease and holds it through removal. Two stable inventories cover
  tracked, untracked, ignored, committed, handoff, symlink, and special-file state.
  Drift, errors, unsupported platform/filesystem proof, or a live lease preserves.
- [ ] IF-0-SCHED-3 — creation never force-removes recoverable state. An occupied or
  preserved generation causes a fresh collision-resistant path and branch, and every
  consumer uses the returned handle.
- [ ] IF-0-SCHED-4 — declared `execution_policy.work_unit_kind` wins at both scheduler
  sites; heuristics are fallback only when no supported kind is declared.
- [ ] IF-0-SCHED-5 — committing closeout transports owned dirty artifacts before parent
  reduction; manual, blocked, failed, conflicting, or ambiguous closeout preserves the
  exact generation, branch, and byte inventory. No-diff skips only artifact-dependent
  verification; a real diff still verifies.
- [ ] IF-0-SCHED-6 — closeout preserves the two surviving historical refs and records
  the accepted unknown worktree loss without claiming recovery.
- [ ] IF-0-SCHED-7 — `SCHED_HARDEN_HANDOFF` binds the actual reviewed SL-2 integration
  identity, tree, exact six-path production set, plan/roadmap
  digests, successor HARDEN plan, canonical receipt, and exact-digest review before
  HARDEN touches overlapping files.

## Lane Index & Dependencies

SL-0 — Ratification record
Depends on: (none)
Blocks: SL-1
Parallel-safe: no

SL-1 — Tests-only successor
Depends on: SL-0
Blocks: SL-2, SL-4
Parallel-safe: no

SL-2 — Scheduler runtime
Depends on: SL-1
Blocks: SL-3
Parallel-safe: no

SL-3 — HARDEN handoff
Depends on: SL-2
Blocks: SL-5
Parallel-safe: no

SL-4 — Worktree authority
Depends on: SL-0, SL-1
Blocks: SL-6
Parallel-safe: yes

SL-5 — HARDEN admission
Depends on: SL-3
Blocks: SL-6
Parallel-safe: yes

SL-6 — Evidence reducer
Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
Blocks: (none)
Parallel-safe: no

## Lanes

### SL-0 — Ratification record

- **Scope**: Consume the landed decision record; do not reinterpret handoffs as checkpoints.
- **Owned files**: `docs/research/sched-worktree-recovery-ratification.md`
- **Interfaces provided**: `SCHED_RECOVERY_DECISION`.
- **Interfaces consumed**: roadmap and current worktree lifecycle (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: verify the record names generation, lease, complete inventory, and residual-loss boundaries.
  - impl: no successor write; preserve the accepted record.
  - verify: require its recorded record-only ancestry and unchanged runtime paths.

### SL-1 — Tests-only successor

- **Scope**: Replace the rejected head with a satisfiable immutable RED contract.
- **Owned files**: `phase-loop-runtime/tests/test_phase_worktree_executor.py`,
  `phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py`,
  `phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py`,
  `phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py`,
  `phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py`,
  `phase-loop-runtime/tests/test_phase_loop_runner.py`,
  `phase-loop-runtime/tests/test_phase_loop_launcher.py`,
  `phase-loop-runtime/tests/test_workerpool_failure_isolation.py`,
  `phase-loop-runtime/tests/test_workerpool_parallel.py`,
  `phase-loop-runtime/tests/test_workerpool_worktree_alloc.py`,
  `phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py`,
  `phase-loop-runtime/tests/test_phase_loop_v45_sched.py`,
  `phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py`
- **Interfaces provided**: `SCHED_RED_SUITE`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`.
- **Parallel-safe**: no.
- **Tasks**:
  - test: keep unguarded `test_create_is_idempotent_after_stale_worktree` as the
    always-green legacy control, but make its fixture empty and its assertions limited
    to successful recreation at the requested base; it must assert neither path reuse
    nor deletion of user bytes. Keep activated
    `test_sched_create_preserves_committed_generation_and_mints_replacement` as the
    recoverable committed-generation falsifier, including the ratification-record
    reference, distinct generation/path/branch, retained ref, and byte identity.
  - test: retain the exact guard and skip reason. Freeze disjoint, complete tuples:
    `SCHED_SL2_NODEIDS` has 12 nodes, `SCHED_SL4_NODEIDS` has 8, and
    `SCHED_JOINED_NODEIDS` has 4. Move
    `test_scheduler_consumes_creator_returned_worktree_handle` from SL-2 to joined;
    the other joined nodes are the three existing supervisor mutation parameters.
    Their 24-node union is exactly every guarded SCHED assertion.
  - test: repair the three mutation nodes with a digest-bound, test-local reference
    supervisor in `test_phase_loop_v45_schedharden.py`. On the exact pre-production
    source digests it must traverse the real runner → `PhaseWorkerJob` →
    `launch_with_spec` → `launch` → `subprocess.Popen` seam, run an unmodified positive
    control, then independently inject: stripped `pass_fds`; disabled session plus
    subreaper; and direct-child-only reaping. Each injection must execute and produce a
    distinct unsafe observation while a helper grandchild is live. Emit one
    `verification_evidence.v3` record per exact nodeid with base/source/restored digests,
    injection anchor and digest, expected failure anchor, observed lock/grandchild state,
    and positive-control result. The fallback fixture is permitted only when the
    production supervisor symbol is absent on that frozen base. Once production exists,
    fixture use is a failure; the joined gate requires `reference_fixture_used=false`
    and reruns the same probes through the real production class and reclamation.
  - test: strengthen `test_launcher_accepts_explicit_nonserialized_lease_authority`.
    After launch custody transfers, close the test/coordinator copy; after coordinator
    and direct executor exit, a separate contender must still fail `flock` while the
    helper grandchild is live. Prove the grandchild is reaped, then prove the contender
    can acquire. Receipt shape is corroboration only and this lane-local test does not
    invoke SL-4 reclamation.
  - verify: without activation, require the thirteen modules green with only exact SCHED
    skips. With `PHASE_LOOP_TDD_EXPECT_SCHED=1`, require intended RED plus the per-node
    mutation records and genuine reference positive controls. Restore every injection,
    run Ruff and `git diff --check`, and require an exact tests-only diff before review.

### SL-2 — Scheduler kind, transport, and supervisor

- **Scope**: Close scheduler selection, identity, artifact, no-diff, and launcher supervision.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_scheduler.py`,
  `phase-loop-runtime/src/phase_loop_runtime/launcher.py`,
  `phase-loop-runtime/src/phase_loop_runtime/models.py`,
  `phase-loop-runtime/src/phase_loop_runtime/plan_ir.py`,
  `phase-loop-runtime/src/phase_loop_runtime/runner.py`,
  `phase-loop-runtime/src/phase_loop_runtime/worker_pool.py`
- **Interfaces provided**: `SCHED_SCHEDULER_RUNTIME`.
- **Interfaces consumed**: `SCHED_RED_SUITE`, injected typed lease capability,
  `DispatchLock.caller_run_id`, `child_executor_env`, and ownership-gated closeout (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: change no SL-1 file; make only the 12-node SL-2 tuple green.
  - impl: `plan_ir.py` must parse lane policy; `models.py` must carry
    `LaneWave.work_unit_kinds` and generation-bearing assignments. Route declared kinds
    at both sites; thread one local run identity; consume creator-returned assignments;
    preserve/transport artifacts; and condition verification on an exact no-diff.
  - impl: propagate the nonserialized descriptor through serial and worker paths. For
    captured and streamed launch, use an independent POSIX supervisor with `pass_fds`,
    session ownership, subreaper semantics, complete-tree reaping, and a bound receipt.
    Before SL-4 publishes authority, only explicit injected capability is active;
    afterwards missing or malformed authority preserves/blocks.
  - verify: run the activated 12-node tuple with zero failure/error/skip, including the
    post-custody flock and grandchild-reaping lease test; joined remains RED.

### SL-3 — Bind scheduler landing into HARDEN

- **Scope**: Bind the actual SL-2 landing before HARDEN writes overlapping runtime files.
- **Owned files**: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`,
  `plans/evidence/v10-SCHED-HARDEN-review.json`
- **Interfaces provided**: `SCHED_HARDEN_HANDOFF`.
- **Interfaces consumed**: `SCHED_SCHEDULER_RUNTIME` and existing HARDEN handoff/receipt contracts.
- **Parallel-safe**: no.
- **Tasks**:
  - test: record the canonical integration identity and verify its exact production set:
    `lane_scheduler.py`, `launcher.py`, `models.py`, `plan_ir.py`, `runner.py`, `worker_pool.py`.
  - impl: preserve every existing HARDEN lifecycle byte and template. Append the current
    authority and candidate handoff using the frozen canonical JSON/digest/receipt schema,
    with that exact six-path `required_path_set`, actual reviewed identity/tree, and
    current SCHED, HARDEN, roadmap, and manifest digests.
  - verify: reject Git config redirects before object lookup, validate candidate plans
    and manifest, obtain a fresh exact-digest native-first board, create the separate
    receipt head, and require it on fetched canonical main before HARDEN starts.

### SL-4 — Worktree lease, generation, and reclamation

- **Scope**: Implement the ratified generation-addressed preserve-by-default lifecycle.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`
- **Interfaces provided**: `SCHED_WORKTREE_AUTHORITY`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`, `SCHED_RED_SUITE`.
- **Parallel-safe**: yes, after SL-1 and disjoint from SL-2/SL-3.
- **Tasks**:
  - test: change no SL-1 file; make only the 8-node SL-4 tuple green.
  - impl: publish generation and typed lease authority; inventory without following
    links; separate owner teardown from released-lease crash reclamation; preserve on
    uncertainty or bytes; mint fresh path/branch for an occupied generation.
  - verify: run the activated 8-node tuple and existing worktree regressions. The real
    handle-to-assignment and launcher/reclamation controls remain joined.

### SL-5 — Admit exact HARDEN completion

- **Scope**: Admit only canonical HARDEN completion without making HARDEN depend on full SCHED.
- **Owned files**: `plans/evidence/v10-SCHED-HARDEN-completion.json`
- **Interfaces provided**: `SCHED_HARDEN_COMPLETION`.
- **Interfaces consumed**: `SCHED_HARDEN_HANDOFF` and canonical HARDEN completion.
- **Parallel-safe**: yes, with SL-4 after SL-3.
- **Tasks**:
  - test: require the unmodified HARDEN verifier and receipt ancestry.
  - impl: record metadata-only commit, tree, event digest, verifier, and exit status.
  - verify: recompute every identity from fetched canonical main.

### SL-6 — Documentation and completion evidence

- **Scope**: Reduce exact-main SCHED evidence after both writers and HARDEN complete.
- **Owned files**: `docs/research/sched-worktree-reclamation-evidence.md`
- **Interfaces provided**: `SCHED_COMPLETION_EVIDENCE`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`, `SCHED_RED_SUITE`,
  `SCHED_SCHEDULER_RUNTIME`, `SCHED_WORKTREE_AUTHORITY`, `SCHED_HARDEN_HANDOFF`,
  `SCHED_HARDEN_COMPLETION`.
- **Parallel-safe**: no.
- **Tasks**:
  - test: replay exact-main proofs and every changed-path boundary.
  - impl: document final behavior and retained historical refs; keep the unknown loss
    explicit. `CHANGELOG.md` remains HARDEN-owned.
  - verify: run the final activated zero-skip gate and record EC-SCHED-7 only as
    `UNMET_ACCEPTED_RESIDUAL`.

## Verification

The SL-1 successor first runs the thirteen frontmatter paths without activation and
requires default green with only the exact guarded skips. Lane gates select the frozen
tuple literally, for example:

```bash
PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests \
python3 -m pytest -q $(PYTHONPATH=phase-loop-runtime/tests python3 -c \
'from test_phase_worktree_executor import SCHED_SL2_NODEIDS; print(*SCHED_SL2_NODEIDS)')
```

Substitute `SCHED_SL4_NODEIDS` only after SL-4 and `SCHED_JOINED_NODEIDS` only after
both landings. Final host verification runs `automation.suite_command` with JUnit and
requires tests > 0 and failures = errors = skips = 0, then runs existing worktree/index
and dispatch-lock regressions, `uv run --locked ruff check .`, `uv lock --check`,
`python3 scripts/check_model_id_sources.py`, `git diff --check`, and final
`python3 -m pytest -q -m "not dotfiles_integration"` from `phase-loop-runtime`.

## Execution Notes

- Record the successor's canonical pre-production base and source digests before any
  test edit. Every mutation and positive control runs on that exact base.
- SL-1 is tests-only; SL-2 is exactly six production paths; SL-4 is exactly one.
  Their landing proofs use actual reviewed integration identities, never future pins.
- A correction to accepted SL-1 requires another reviewed tests-only successor.

## Acceptance Criteria

- [ ] EC-SCHED-0 — proven by `git merge-base --is-ancestor "$SCHED_SL1_LANDING" "$SCHED_SL2_LANDING" && git merge-base --is-ancestor "$SCHED_SL1_LANDING" "$SCHED_SL4_LANDING"` plus `verification_evidence.v3` records binding the exact 13-test, six-path SL-2, and one-path SL-4 diffs; falsified by production preceding SL-1, a non-biting mutation, a wrong path set, or a test path in either production diff.
- [ ] EC-SCHED-1 — proven by `PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_create_preserves_committed_generation_and_mints_replacement`; falsified by path-entered control: unconditional force removal deletes the preserved generation.
- [ ] EC-SCHED-2 — proven by `PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py::test_create_is_idempotent_after_stale_worktree phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_create_preserves_committed_generation_and_mints_replacement`; falsified by the legacy control asserting deletion/path reuse or the activated replacement omitting its decision reference or preservation assertion.
- [ ] EC-SCHED-3 — proven by `PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_ignored_handoff_only_generation_is_preserved`; falsified by path-entered control: ignored handoff content is classified empty and removed.
- [ ] EC-SCHED-4 — proven by `PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py::test_declared_work_unit_kind_is_authoritative_at_lane_selection phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py::test_declared_phase_reducer_kind_bypasses_executor_heuristic`; falsified by path-entered control: either selection site restores heuristic precedence.
- [ ] EC-SCHED-5 — proven by `PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_v45_sched.py::test_staged_planner_artifact_survives_parent_reduction phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_create_preserves_dirty_and_untracked_generation_bytes_and_ref`; falsified by destructive reduction/teardown while the positive reduction control still executes.
- [ ] EC-SCHED-6 — proven by `PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py::test_no_diff_result_requires_an_explicit_artifact_verification_skip phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py::test_real_diff_never_skips_artifact_dependent_verification`; falsified by path-entered control: no-diff verifies or real-diff skips.
- [ ] EC-SCHED-7 — state remains `UNMET_ACCEPTED_RESIDUAL`; proven only by `git ls-remote origin refs/heads/feat/advisor-board-abdreg refs/heads/phase/abdresolve` plus the exact-main evidence record; falsified by a missing ref without decision or any claim that unknown bytes were recovered.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`, runtime/test owned paths, and SCHED evidence docs
- evidence paths: `plans/phase-plan-v10-SCHED.md`, `plans/evidence/v10-SCHED-HARDEN-review.json`, `plans/evidence/v10-SCHED-HARDEN-completion.json`, `docs/research/sched-worktree-reclamation-evidence.md`
- redaction posture: `metadata_only`
- downstream handling: exact six-path SL-2 handoff and fresh HARDEN review; roadmap bytes remain unchanged
