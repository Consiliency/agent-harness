---
phase_loop_plan_version: 1
phase: SCHED
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 6b2e6cabe9b6728e0f0639ea79497d92ec17ee2ab74d583e56b883ab79f0fc68
automation:
  suite_command: 'PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_phase_worktree_executor.py phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py phase-loop-runtime/tests/test_phase_loop_runner.py phase-loop-runtime/tests/test_phase_loop_launcher.py phase-loop-runtime/tests/test_workerpool_failure_isolation.py phase-loop-runtime/tests/test_workerpool_parallel.py phase-loop-runtime/tests/test_workerpool_worktree_alloc.py phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py phase-loop-runtime/tests/test_phase_loop_v45_sched.py phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py'
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

The phase has two production writers, matching the roadmap: the scheduler cluster and
worktree reclamation. Control lanes enforce a separately reviewed decision record, one
tests-only RED boundary before either writer, and a post-implementation evidence/docs
reducer. The scheduler writer lands first and becomes a HARDEN input before HARDEN
touches `runner.py` or `launcher.py`; the reclamation writer is disjoint and may proceed
independently after the recorded decision. Full SCHED closeout waits for both writers and
HARDEN. All SL-1 tests are immutable after their tests-only landing. Production PRs may
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
  committing closeout, while manual/failed/ambiguous closeout preserves the exact child
  generation, branch, and byte inventory without teardown. A branch ref alone is not
  recovery evidence. No-diff work skips artifact-dependent phase verification without
  skipping verification for a real diff.
- [ ] IF-0-SCHED-6 — the SCHED disposition records the two surviving historical branch
  tips and the accepted possible loss from the removed `phase/abdresolve` worktree
  without claiming that unknown work was recovered.
- [ ] IF-0-SCHED-7 — `SCHED_HARDEN_HANDOFF` binds the actual SL-2 landing commit, tree,
  exact production path set, reviewed SCHED plan/roadmap digests, successor HARDEN plan
  digest, and a domain-separated digest of the canonical handoff object stored in the
  successor manifest. A separate receipt head binds the exact reviewed candidate manifest
  blob without self-reference. HARDEN may not begin an overlapping write until that
  candidate has a fresh converged exact-digest native-first board review and the receipt
  topology validates.

## Lane Index & Dependencies

SL-0 — Ratify leased generational recovery
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no

SL-1 — Immutable tests-only RED boundary
  Depends on: SL-0
  Blocks: SL-2, SL-4
  Parallel-safe: no

SL-2 — Scheduler kind, artifact transport, and no-diff dispatch
  Depends on: SL-1
  Blocks: SL-3, SL-5
  Parallel-safe: no

SL-3 — Bind scheduler landing into HARDEN
  Depends on: SL-2
  Blocks: SL-5
  Parallel-safe: no

SL-4 — Worktree lease, generation, and conservative reclamation
  Depends on: SL-0, SL-1
  Blocks: SL-6
  Parallel-safe: yes (with SL-2 after SL-1)

SL-5 — Admit exact HARDEN completion
  Depends on: SL-3
  Blocks: SL-6
  Parallel-safe: yes (with SL-4)

SL-6 — Documentation, disposition, and completion evidence
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

## Delivery Boundaries

1. The planning package carries an exact-digest native-first board review artifact.
2. The SL-0 closeout records a record-only changed-path set and the reviewed canonical
   main ancestry before test authorship begins.
3. The SL-1 closeout records a tests-only changed-path set and panelled RED evidence.
   Its test paths are immutable for SL-2 through SL-6.
4. The SL-2 scheduler closeout records a production-only changed-path set and precedes
   HARDEN. HARDEN consumes that exact landing before touching any overlapping writer.
5. The SL-3 governance closeout records the actual SL-2 commit/tree/path set in a
   successor HARDEN plan and manifest, and binds a fresh exact-digest native-first review.
   HARDEN cannot start an overlapping write before that review converges.
6. The SL-4 reclamation closeout records a production-only changed-path set disjoint
   from HARDEN and may proceed independently after SL-0 and SL-1.
7. The SL-5 control closeout admits only an exact validated HARDEN completion landing.
8. The SL-6 closeout runs only after SL-2, SL-3, SL-4, and SL-5; it records
   exact-main replay, the accepted historical residual, and every changed-path boundary.

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
  - test: add falsifiers for same-phase committed work, dirty/untracked state, an ignored
    `.dev-skills/handoffs/`-only candidate, a held live lease, post-scan mutation, lease
    identity drift, and generation/path/branch collision. Assert that each preserves the
    old generation, its ref, and byte-exact recoverable content.
  - test: add a positive control proving a released-lease candidate with an exact empty
    inventory can be reclaimed and a fresh generation can launch.
  - test: add production-path tests proving declared `lane_execute` overrides a reducer
    heuristic and declared `phase_reducer` overrides an executor heuristic at both sites;
    nested dispatch carries one run identity through the real launcher/worker boundary; a
    staged planner artifact survives concurrent parent reduction; manual/blocked closeout
    leaves the exact child generation readable with unchanged staged and untracked bytes;
    no-diff skips only artifact-dependent verification; a real diff still verifies.
  - test: run every mutation against the exact pre-production base, require the injection
    anchor to execute, record expected RED, restore the source, and record unchanged
    positive controls.
  - verify: run the thirteen owned modules plus Ruff and `git diff --check`; require the new
    falsifiers RED for the intended reason and all unrelated existing tests green.

### SL-2 — Scheduler kind, artifact transport, and no-diff dispatch

- **Scope**: Close the scheduler cluster before HARDEN: honor declared work-unit kind,
  thread one local run identity through the real child boundary, preserve child artifacts,
  and avoid artifact-dependent verification on an exact no-diff result.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_scheduler.py`,
  `phase-loop-runtime/src/phase_loop_runtime/runner.py`,
  `phase-loop-runtime/src/phase_loop_runtime/launcher.py`,
  `phase-loop-runtime/src/phase_loop_runtime/worker_pool.py`
- **Interfaces provided**: `SCHED_SCHEDULER_RUNTIME`.
- **Interfaces consumed**: `SCHED_RED_SUITE`, `PhaseWorktreeHandle` (pre-existing),
  `DispatchLock.caller_run_id` (pre-existing), `child_executor_env` (pre-existing), and
  ownership-gated closeout (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - impl: prefer a valid declared `lane_execute`/`phase_reducer` kind at both scheduler
    sites, retaining the current heuristics only for undeclared legacy plans.
  - impl: thread one local run identity through `DispatchLock`, `PhaseWorkerJob`,
    `launch_with_spec`, and the child executor env without mutating process-global
    environment; genuine competing runs retain normal contention.
  - impl: consume the exact `PhaseWorktreeHandle` path/branch returned by creation and
    never reconstruct a live assignment from phase, branch, or lane strings.
  - impl: transport staged/dirty planning output before parent reduction only under
    commit/push closeout; on manual closeout, transport conflict, block, or failed adoption,
    skip teardown, preserve the exact generation and branch with a stable byte inventory,
    and emit a recoverable typed event.
  - impl: skip artifact-dependent phase verification only after a production result proves
    an exact no-diff; retain normal verification for any real diff or ambiguous result.
  - verify: make the SL-1 scheduler tests green without changing them; run lane scheduler,
    concurrent dispatch, work-unit, launcher, worker-pool, dispatch-lock, and runner suites.

### SL-3 — Bind scheduler landing into HARDEN

- **Scope**: Turn the actual reviewed SL-2 landing into an executable downstream
  dependency before HARDEN touches either overlapping runtime file.
- **Owned files**: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`,
  `plans/evidence/v10-SCHED-HARDEN-review.json`
- **Interfaces provided**: `SCHED_HARDEN_HANDOFF`.
- **Interfaces consumed**: `SCHED_SCHEDULER_RUNTIME`, exact canonical Git objects, and
  the current HARDEN contract record (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - impl: fetch canonical main and require the exact reviewed SL-2 landing to be its
    ancestor; record the landing commit/tree and require its diff to equal only
    `lane_scheduler.py`, `runner.py`, `launcher.py`, and `worker_pool.py`.
  - impl: create candidate `C` by amending HARDEN context, consumed interfaces, overlap
    inventory, and preflight so they require the actual SL-2 landing before any `runner.py`
    or `launcher.py` write. Append one manifest lifecycle event whose domain-separated
    `manifest_contract_sha256` covers canonical compact sorted-key JSON of only the
    `sched_harden_handoff` object with that digest field excluded: SHA-256 over the UTF-8
    `manifest_contract_digest_domain` bytes followed by the compact JSON bytes and one LF.
    Duplicate keys, floats, surrogates, and non-UTF-8 data reject. Its exact key set is
    `actual_sl2_commit`, `actual_sl2_tree`, `handoff_status`, `harden_plan_sha256`,
    `manifest_contract_digest_domain`, `manifest_contract_sha256`, `required_path_set`,
    `required_review_seats`, `review_receipt_path`, `roadmap_sha256`, `schema`, and
    `sched_plan_sha256`; candidate values are non-null and status is `candidate_awaiting_review`.
  - verify: recompute the roadmap, SCHED, HARDEN, and manifest contract digests, validate
    both plans and the manifest at `C`, then obtain a fresh exact-digest native-first
    four-seat board over `C`. Any dissent, timeout, missing seat, or digest drift blocks.
  - impl: only after convergence, create single-parent receipt head `R` whose sole diff
    from `C` is `plans/evidence/v10-SCHED-HARDEN-review.json`. The canonical receipt binds
    `C` commit/tree, exact HARDEN plan and manifest blob/digests, the domain-separated
    manifest contract digest, every seat's native artifact identity/status/verdict, and
    requires all four usable terminal verdicts to be `AGREE`. The receipt contains no
    self-digest; its Git blob OID is the retained identity.
  - verify: HARDEN preflight requires `R^ == C`, `C..R` exactly the receipt path, unchanged
    plan/manifest blobs, non-null actual SL-2 identities, exact four-path SL-2 diff, valid
    contract digest, and a canonical converged receipt before any overlapping write.

### SL-4 — Worktree lease, generation, and conservative reclamation

- **Scope**: Implement the ratified lifetime lease and generation-addressed,
  preserve-by-default worktree lifecycle without interpreting handoffs as checkpoints.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`
- **Interfaces provided**: `SCHED_WORKTREE_AUTHORITY`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`, `SCHED_RED_SUITE`, and existing
  Git worktree index and path primitives (pre-existing).
- **Parallel-safe**: yes, after SL-1 and disjoint from SL-2 and SL-3.
- **Tasks**:
  - impl: acquire and retain a kernel lifetime lease before exposing an active handle;
    release it only after successful teardown or a preservation receipt. Do not rely on
    PID, mtime, directory age, or handoff presence as liveness authority.
  - impl: enumerate tracked, untracked, ignored, committed, symlink, and special-file
    state without following links; compare stable pre/post identities and fail closed on
    unreadable or changing paths.
  - impl: preserve every candidate carrying any recoverable state. Reclaim only a proven
    inactive, empty generation and revalidate immediately before removal; never use
    `--force` as a substitute for the lease/inventory proof.
  - impl: when the canonical generation is occupied or preserved, mint a collision-resistant
    path and temporary branch inside this module and return those exact values. Preserve all
    older generations and branches; a branch ref never substitutes for dirty bytes.
  - verify: make the SL-1 worktree tests green without changing them; run all existing
    phase-worktree and worktree-index regressions.

### SL-5 — Admit exact HARDEN completion

- **Scope**: Turn the external HARDEN completion landing into an explicit internal SCHED
  dependency without making full SCHED a prerequisite of HARDEN.
- **Owned files**: `plans/evidence/v10-SCHED-HARDEN-completion.json`
- **Interfaces provided**: `SCHED_HARDEN_COMPLETION`.
- **Interfaces consumed**: `SCHED_HARDEN_HANDOFF` and the exact canonical HARDEN
  completion landing.
- **Parallel-safe**: yes, with SL-4 after SL-3.
- **Tasks**:
  - verify: fetch canonical main and require the HARDEN completion topology, plan/roadmap
    digests, manifest lifecycle, final audit/evidence, and mandatory review receipt to pass
    the unmodified HARDEN verifier; reject branch-local or self-authored summaries.
  - impl: write canonical metadata-only evidence binding the fetched HARDEN landing commit,
    tree, completion event digest, verifier identity, and successful exit status.
  - verify: re-open the evidence, recompute every Git object and digest, and require its
    landing ancestry to contain receipt head `R` before SL-6 may start.

### SL-6 — Documentation, disposition, and completion evidence

- **Scope**: Reconcile public scheduler documentation and reduce exact-main evidence after
  both implementation landings.
- **Owned files**: `docs/research/sched-worktree-reclamation-evidence.md`
- **Interfaces provided**: `SCHED_COMPLETION_EVIDENCE`.
- **Interfaces consumed**: `SCHED_RECOVERY_DECISION`, `SCHED_RED_SUITE`,
  `SCHED_WORKTREE_AUTHORITY`, `SCHED_SCHEDULER_RUNTIME`, `SCHED_HARDEN_HANDOFF`,
  `SCHED_HARDEN_COMPLETION`, and exact
  canonical commits (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - impl: document lease-backed generation behavior, preserve-by-default recovery, and
    the no-checkpoint boundary; describe declared-kind and planner-artifact behavior in
    the SCHED evidence record without changing HARDEN-owned changelog bytes.
  - no-doc-change decision: `CHANGELOG.md` is intentionally excluded because HARDEN owns
    its Unreleased bytes across the required SL-2-to-HARDEN writer handoff; the dedicated
    SCHED evidence record is the truthful phase-local documentation surface.
  - impl: record the two surviving historical branch tips from fresh canonical remote
    metadata and retain the `phase/abdresolve` unknown-loss finding as unmet historical
    state, never as recovered work.
  - verify: after HARDEN completion, run the full phase suite on exact canonical main,
    validate that SL-2 precedes HARDEN and every changed-path boundary is exact, then
    produce metadata-only verification evidence. Record EC-SCHED-7 as
    `UNMET_ACCEPTED_RESIDUAL`, never green.

## Verification

Run from the repository root unless stated otherwise.

```bash
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  phase-loop-runtime/tests/test_phase_worktree_executor.py \
  phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py \
  phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py \
  phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py \
  phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py \
  phase-loop-runtime/tests/test_phase_loop_runner.py \
  phase-loop-runtime/tests/test_phase_loop_launcher.py \
  phase-loop-runtime/tests/test_workerpool_failure_isolation.py \
  phase-loop-runtime/tests/test_workerpool_parallel.py \
  phase-loop-runtime/tests/test_workerpool_worktree_alloc.py \
  phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py \
  phase-loop-runtime/tests/test_phase_loop_v45_sched.py \
  phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py
```

The worker-pool integration gate must run in a host checkout with a reachable dotfiles
fleet tree; a skipped test is a failure:

```bash
tmp_junit="$(mktemp)"
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q \
  --junitxml="$tmp_junit" \
  phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py \
  phase-loop-runtime/tests/test_phase_loop_v45_sched.py \
  phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py
python3 - "$tmp_junit" <<'PY'
import sys
import xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
totals = {key: sum(int(s.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
assert totals["tests"] > 0 and totals["failures"] == totals["errors"] == totals["skipped"] == 0, totals
PY
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

- SL-0 through SL-6 produce distinct review-boundary receipts. The coordinator
  records each canonical target tip, reviewed head, resulting ancestry, and exact
  changed-path set before advancing.
- The SL-1 RED evidence uses `verification_evidence.v3`. Each mutation record carries
  the exact nodeid, source anchor, mutation digest, expected failure anchor, restored
  source digest, and positive-control result. A missing or non-biting mutation blocks.
- The implementation may not change any SL-1 owned file. A test correction requires a
  new separately reviewed tests-only successor before further production edits.
- SL-2 is the roadmap's lane B and must be reviewed and integrated before SL-3 binds its
  exact landing into HARDEN. HARDEN may begin an overlapping writer only after the SL-3
  successor plan/manifest also receives a fresh exact-digest review. SL-5 admits the
  exact HARDEN completion as an internal gate for SL-6. SL-4 is the disjoint roadmap lane
  A and does not wait for SL-2.
- The final reducer replays the exact merged bytes from canonical main; branch-local
  evidence, self-authored summaries, or a stale worktree cannot complete SCHED. It
  reports seven satisfied criteria plus EC-SCHED-7 as an accepted unmet residual, never
  eight green criteria.

## Acceptance Criteria

- [ ] EC-SCHED-0 — proven by `git diff --name-only "$SCHED_SL1_BASE..$SCHED_SL1_LANDING"`
  equaling the thirteen SL-1 paths and by two independent production landing proofs. For the
  scheduler writer, require `git merge-base --is-ancestor "$SCHED_SL1_LANDING"
  "$SCHED_SL2_LANDING^1"` and an exact four-path SL-2 diff. For the reclamation writer,
  require `git merge-base --is-ancestor "$SCHED_SL1_LANDING" "$SCHED_SL4_LANDING^1"`
  and an exact one-path SL-4 diff. Neither diff may contain an SL-1 path; both proofs feed
  the `verification_evidence.v3` reducer. Falsified by either production landing preceding
  the tests landing, a non-biting RED mutation, a wrong production path set, or any SL-1
  path in either production diff;
  path-entered control: the unchanged tests-only candidate traverses the activated RED
  chronology, restores every injection, and reaches the default-green positive controls.
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
  declared_work_unit_kind`; falsified by path-entered mutations at either scheduler site
  that route declared `phase_reducer` through the executor path or declared `lane_execute`
  through the reducer path.
- [ ] EC-SCHED-5 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py
  -k 'staged_plan or preserves_dirty_generation'`; falsified by a path-entered
  committed-only reduction or teardown that removes/overwrites the validated planner
  artifact, or leaves only a branch ref from which the staged/untracked bytes cannot be
  retrieved, while the positive reduction control runs.
- [ ] EC-SCHED-6 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  python3 -m pytest -q phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py
  -k 'no_diff or real_diff'`; falsified by a path-entered no-diff result reaching
  artifact-dependent verification or by a real diff bypassing verification.
- [ ] EC-SCHED-7 — state: `UNMET_ACCEPTED_RESIDUAL`, never green. The closeout runs
  `git ls-remote origin refs/heads/feat/advisor-board-abdreg
  refs/heads/phase/abdresolve`, records the retained committed tips, and repeats that the
  removed `phase/abdresolve` worktree's 25 uncommitted files remain unknowable; falsified by
  either remote ref disappearing without a recorded decision, by the reducer claiming
  the unknown bytes were recovered, or by any summary reporting EC-SCHED-7 as passed.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `specs/phase-plans-v10.md`, `plans/phase-plan-v10-HARDEN.md`,
  `plans/manifest.json`, `docs/research/sched-worktree-recovery-ratification.md`,
  `docs/research/sched-worktree-reclamation-evidence.md`
- evidence paths: `plans/phase-plan-v10-SCHED.md`,
  `plans/evidence/v10-SCHED-HARDEN-review.json`,
  `plans/evidence/v10-SCHED-HARDEN-completion.json`,
  `docs/research/sched-worktree-reclamation-evidence.md`
- redaction posture: `metadata_only`
- downstream handling: SL-3 must rebind the actual SL-2 landing into HARDEN and obtain a
  fresh exact-digest native-first review before HARDEN begins overlapping writes
