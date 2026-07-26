# Detailed plan: scheduler-dispatch cluster — self-block on own lock (ah#301) + concurrent planner-artifact data loss (ah#300)

## Task
Two coupled defects in the phase-loop scheduler-dispatch subsystem (adjacent code, one reviewer context):

- **Consiliency/agent-harness#301** — resuming an executing multi-lane phase with `--lane-scheduler serialized`
  dispatches the first work unit as `phase_reducer` instead of the plan-declared `lane_execute`; the injected
  native execute-phase executor then refuses to write with `blocker_class=concurrent_dispatch`, produces no
  diff, and the parent runs phase verification against implementation files that were never created.
- **Consiliency/agent-harness#300** — with `--phase-scheduler concurrent --full-phase`, two planning workers
  validate their exact phase-plan artifacts in isolated child worktrees and exit 0, but the parent reducer
  checks only the clean parent worktree, classifies both plans missing, blocks both phases, then deletes the
  child worktrees/branches — discarding the only validated copy (data loss).

Both are **fully in-repo, runtime-only** fixes. No skill-bundle edit is required (see the #301 correction below).

## Research summary (source-verified on `phase-loop-runtime/` at branch `feat/fab-265-merge-queue-bound`; both issues filed against 0.7.10)

### IMPORTANT correction to the triage hand-off (#301 has NO out-of-repo leg)
The triage stated the self-concurrency check "lives in the INJECTED execute-phase skill, not the runtime,"
making a runtime-only fix incomplete. **That is wrong — verified by exhaustive trace.** The
`blocker_class=concurrent_dispatch` value is emitted at **exactly one place**: `runner.py:1466` and
`runner.py:1482`, inside the `except DispatchLockContention` handler for the single `DispatchLock(...)`
construction at `runner.py:1462` (grep across the tree finds no other emitter; `models.py:144` is only the
enum literal). No execute-phase skill source (`skills-src/*/*-execute-phase/`, neutral
`phase-loop-skills/execute-phase/`, or the generated `skills_bundle/*-execute-phase/`) contains any
concurrent-run / active-work-unit / heartbeat / self-dispatch refusal text or the string `concurrent_dispatch`.
**The refusal is the runtime's per-roadmap DispatchLock, not the skill.** The fix is entirely in
`phase-loop-runtime/src/phase_loop_runtime/`.

### #301 — two independent runtime defects

**Defect 1 — work-unit kind is re-derived from a fragile body-text heuristic, ignoring the plan's declared
`work_unit_kind`.** Both scheduler dispatch sites recompute `kind` from lane attributes instead of honoring
the plan's `execution_policy.work_unit_kind`:
- `runner.py:5227` (inside `_launch_ready_lane_wave`, def at `runner.py:5155`):
  `kind = "phase_reducer" if lane.reducer_kind != "none" or lane.read_only else "lane_execute"`.
- `runner.py:5363` (its twin inside `select_next_work_unit`, def at `runner.py:5343`):
  `kind = "phase_reducer" if lane.reducer_kind != "none" or not lane.owned_files else "lane_execute"`.

The declared kind IS available: `PhasePlanLane.execution_policy` is an `ExecutionPolicyRule`
(`plan_ir.py:320`, `execution_policy=policy`) whose `work_unit_kind` field is populated from the plan's
`work_unit=` assignment (`discovery.py:975`, `work_unit_kind=assignments.get("work_unit")`;
`execution_policy_for_lane` at `discovery.py:918`). `select_next_work_unit` even reads
`lane.execution_policy.to_json()` at `runner.py:5368` — so the object is in hand and simply not consulted for
the kind.

The heuristic mis-fires because `reducer_kind` comes from `detect_reducer_lane` (`plan_ir.py:233`, wired at
`plan_ir.py:319`), which returns non-`"none"` whenever the lane id/name/**body** contains `"verify"`,
`"verification"`, `"acceptance"`, `"summary"`, `"final"`, or `"compatibility"`. A normal writer lane routinely
carries a `Verify:` task list in its body (that list is parsed at `plan_ir.py:289-292`), so
`detect_reducer_lane` returns `"verification_reducer"` for an ordinary `lane_execute` lane → the scheduler
dispatches it as `phase_reducer`. This is the root of the SL-1 mis-dispatch.

**Defect 2 — the nested scheduler-dispatched executor cannot recognize its own outer DispatchLock, so it
self-blocks.** Mechanism (traced end to end):
1. `_launch_ready_lane_wave` only *records* the work unit `running` (`launch_work_unit_attempt`,
   `runner.py:5465`, writes state + a `running` event; it launches no executor) and returns `executing`.
2. On the next resume, the lane-scheduler branch does not re-fire (it is gated on `planned`/`executed`); the
   launch-action resolver maps `executing` + a current plan-doc to `launch_action="execute"` and
   `_dispatch_phase` → `launch_with_spec` launches the injected native executor **in-process, under the
   parent's still-held lock** (the lock is acquired at `runner.py:1462` and held across the dispatch body via
   `with dispatch_lock_context, …` — search for `dispatch_lock_context` and `def _dispatch_phase`).
3. The default scheduler-lane executor is `pi` (`capability_registry.py:20`, `DEFAULT_LANE_EXECUTOR = "pi"`;
   `default_executor_for_work_unit` at `capability_registry.py:765-768`). The injected executor's workflow
   header runs a **nested** phase-loop-style command (`pi-agent-watch --phase-plan …`, or literally
   `phase-loop execute {plan}` for the `command`/`grok` executors — search for these in `injection.py`), which
   re-enters `run_loop` for the **same roadmap** and re-acquires the **per-roadmap** DispatchLock at
   `runner.py:1462`.
4. Re-entrancy fails closed. `holder_is_self` (`dispatch_lock.py:101-130`) grants re-entry only on
   (a) `caller_run_id == holder_run_id` (`dispatch_lock.py:121`) or (b) PID ancestry (`_pid_is_ancestor`,
   `dispatch_lock.py:70-98`, used at `:128`). **Neither holds:** the sole construction site
   `runner.py:1462` passes **no `caller_run_id`** (so the lock file records no `run_id` — written only if
   present, `dispatch_lock.py:206-207` — and the nested caller supplies none, leaving the run_id branch dead),
   and the child executor is spawned with `start_new_session=True` (search for `start_new_session` in
   `launcher.py`), which reparents it so the holder pid is no longer an ancestor. Result:
   `DispatchLockContention` → `blocker_class=concurrent_dispatch` (`runner.py:1466/1482`), no diff. The
   "active healthy heartbeat belonging to the very runner that invoked it" in the issue **is** the live,
   parent-held lock file (`blocker_summary` reports the holder PID and elapsed seconds,
   `dispatch_lock.py:146-155`).

The `DispatchLock` class already fully supports the fix — `__init__` accepts `caller_run_id`
(`dispatch_lock.py:159-166`), matches on it (`:121`), and writes it to the lock file (`:206-207`). The design
comment there names **RUNCORE2** as the owner of "injecting this at the runner call sites." It was never
wired: `child_executor_env` (`harness_env_signatures.py:194-206`) stamps only `PHASE_LOOP_CHILD=1`
(`:205`), no run id, and `dispatch_lock.py` reads no environment at all. **Defects 1 and 2 are independent:**
fixing the kind (Defect 1) still routes to a native executor (`pi`) that nests and self-blocks, so Defect 2
must be fixed too; the issue lists both.

### #300 — concurrent planner artifact is silently dropped, then the only copy is deleted
`_dispatch_concurrent_wave` (`runner.py:4548`) picks a transport per a global env flag:
`real_exec_integration = concurrent_real_exec_integration_enabled()` (`runner.py:4564`). When ON it uses
`transfer_phase_worktree_dirty` (`runner.py:4666`); when OFF (the default) it uses `integrate_phase_worktree`
(`runner.py:4690`). Planning workers leave the plan artifact + `plans/manifest.json` **staged/dirty and
uncommitted** in the child worktree (per the issue). `integrate_phase_worktree`
(`phase_worktree_executor.py:235`) is a **committed-only** `--no-ff` merge: with no commits on the child temp
branch it returns `integrated=True, had_commits=False` ("no commits to integrate",
`phase_worktree_executor.py:260-269`) — a **silent no-op**, so nothing reaches the parent worktree.

`_finalize_phase_launch` (`runner.py:3451`, called at `runner.py:4711`) then resolves the current plan against
the **main** repo — `post_launch_plan = find_plan_artifact(repo, alias, …)` (`runner.py:3717`) — finds nothing,
and the missing-plan guard (`runner.py:4104-4163`, gated on `launch_action == "plan"` and
`post_launch_plan is None`) blocks with `repeated_verification_failure` and the message "Planning turn for
{alias} exited successfully but did not create a current phase plan artifact." (`runner.py:4155`). Finally the
wave's teardown (`runner.py:4724-4731`) runs `teardown_phase_worktree(repo, handle,
delete_branch=ready_phase not in preserve_branches)` — and because a **blocked-by-missing-plan** phase is never
added to `preserve_branches` (only integration/transfer *conflicts* are, `runner.py:4676/4697`), the child
branch **and** worktree are deleted. The validated staged plan survives only in runner logs. This is a
**data-loss ordering bug**: teardown deletes the only copy after finalize blocks.

Serial mode does not hit this: the planning turn writes the artifact directly into the **main** repo `plans/`,
so `find_plan_artifact` (`runner.py:3717`) finds it and (`runner.py:4067-4068`) adopts it; the ownership-gated
phase closeout commits it under `--closeout-mode commit|push`. `transfer_phase_worktree_dirty`
(`phase_worktree_executor.py:306-364`) is the existing primitive that reproduces this for a worktree child:
it `git add -A` + commits onto the temp branch (work preserved on a ref), then transports base..temp onto the
main working tree via `git apply` as **unstaged** changes, so the parent's existing selective, ownership-gated
closeout `git add -- <owned>` commits it exactly as in serial mode.

**Footgun to respect (`runner.py:1328-1338`):** real-exec concurrent transport lands dirty work on main that
only a committing closeout (`commit`/`push`) commits before the next wave; under `--closeout-mode manual` it
strands. The startup guard raises when `phase_scheduler_mode == "concurrent"` and `closeout_mode == "manual"`
and `concurrent_real_exec_integration_enabled()`. Routing **plan** artifacts through dirty-transport under
`manual` closeout would recreate the same stranding, so the #300 fix must gate on closeout mode.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify — #301 Defect 1: honor declared kind)
- **Add** a module-level helper `_resolved_work_unit_kind(lane) -> str` (place it just above
  `_launch_ready_lane_wave`, search for `def _launch_ready_lane_wave`). Body: prefer the plan's declared kind
  when present and valid — `declared = lane.execution_policy.work_unit_kind if lane.execution_policy else None`;
  if `declared in {"lane_execute", "phase_reducer"}` return it; otherwise fall back to the **existing**
  heuristic. Keep the two current fallbacks byte-identical to avoid behavior drift on plans that declare no
  `work_unit`: the wave site's fallback uses `lane.reducer_kind != "none" or lane.read_only`; the
  `select_next_work_unit` site's uses `lane.reducer_kind != "none" or not lane.owned_files`. Because the two
  fallbacks differ, give the helper a `fallback_read_only_signals: bool` parameter (or two thin wrappers) so
  each call site keeps its own fallback exactly. Reason: a plan that declares `work_unit_kind` is authoritative;
  the body-text heuristic is a last resort only for plans that declare nothing.
- **Modify** `runner.py:5227`: replace the inline ternary with the helper (wave-site fallback). Reason: a
  writer lane carrying a `Verify:` task must dispatch as `lane_execute` when the plan declares it, not
  `phase_reducer`.
- **Modify** `runner.py:5363`: replace the inline ternary with the helper (`select_next_work_unit` fallback).
  Reason: same defect, twin site; both must move together or serialized vs. concurrent paths diverge.
- Do **not** change `default_executor_for_work_unit` (`capability_registry.py:765-768`): once the kind is
  correct, its routing (`lane_execute` scheduler-assigned → `DEFAULT_LANE_EXECUTOR`) is already right.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify — #301 Defect 2: thread a stable run id)
- **Establish a run-scoped identity at `run_loop` entry, before the lock is taken** (search for
  `def run_loop` at `runner.py:1225`, and the acquire at `runner.py:1462`). Compute
  `run_id = os.environ.get("PHASE_LOOP_RUN_ID") or <mint a stable id>`. Reading `os.environ` here is correct
  **only because a nested `run_loop` is a distinct subprocess** whose inherited env carries the parent's
  `PHASE_LOOP_RUN_ID` (set on the child env dict at spawn — see below), so it reads its **own** process env, not
  a leaked value. Minting when absent: prefer an id already tied to this run (e.g. the run-root artifact dir
  name — `artifacts["root"].name` is used as a run identity elsewhere, `runner.py:3896`); otherwise
  `uuid.uuid4().hex`. The reuse-from-env rule makes a nested invocation present the *same* id, while a genuine
  top-level competitor started by the operator has no such env var and mints its own.
- **CRITICAL — do NOT mutate the parent process's `os.environ`.** Setting `os.environ["PHASE_LOOP_RUN_ID"]` in
  the parent leaks the id across sequential in-process `run_loop` calls (pytest calls `run_loop` many times in
  one process; the #300 concurrent test would spuriously re-enter a stale lock). Keep `run_id` a local, thread
  it explicitly into the child env dict at the spawn site (below), and leave `os.environ` untouched so every
  top-level `run_loop` mints fresh.
- **Modify** `runner.py:1462`: pass it through — `DispatchLock(repo, roadmap, caller_run_id=run_id).acquire()`.
  Reason: the holder then records `run_id` in the lock file (`dispatch_lock.py:206-207`) and a nested caller
  presenting the same `run_id` re-enters via the `run_id` branch (`dispatch_lock.py:121`), which survives the
  `setsid`/`start_new_session` split that defeats PID ancestry. Fail-closed behavior for real competitors is
  unchanged (different or absent id → contention as today).
- Note: this is the RUNCORE2 wiring the `DispatchLock` design comment (`dispatch_lock.py:162-166`) already
  anticipated; no `dispatch_lock.py` change is required for the primary fix.

### `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py` (modify — #301 Defect 2: propagate id to children)
- **Modify** `child_executor_env` (`harness_env_signatures.py:194-206`): accept the run id as an explicit
  **parameter** (`run_id: str | None = None`) threaded from the spawn site, and — after stamping
  `PHASE_LOOP_CHILD=1` (`:205`) — stamp `e["PHASE_LOOP_RUN_ID"] = run_id` when it is provided. Thread the value
  from `run_loop`'s local `run_id` to each `child_executor_env(...)` call at the executor-spawn sites (search
  for `child_executor_env(` uses). **Do not** read the parent's `os.environ` inside `child_executor_env` to
  discover the id (that reintroduces the same-process leak); the id must arrive by parameter so only spawned
  subprocesses carry it. Add a `PHASE_LOOP_RUN_ID_ENV = "PHASE_LOOP_RUN_ID"` constant next to
  `PHASE_LOOP_CHILD_ENV` (`harness_env_signatures.py:35`). Reason: the nested executor's `run_loop` reads this
  from its own inherited subprocess env to present its outer run's id as `caller_run_id`, closing the
  re-entrancy loop across the process-group split — without leaking across in-process calls.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify — #300 fix 1: preserve-before-teardown, MANDATORY)
- **Modify** `_dispatch_concurrent_wave` at the `_finalize_phase_launch` call site (`runner.py:4711`): after
  finalize, if the phase's post-finalize status is `blocked` (finalize could not adopt the child's work — the
  missing-plan block at `runner.py:4104-4163`, or any block), **add `ready_phase` to `preserve_branches`**
  before the `finally` teardown (`runner.py:4724-4731`) runs. Read the status from the finalize outcome
  (`wave_outcome.status_after_closeout`, already inspected at `runner.py:4715`) or re-`reconcile`. Reason: this
  is the unambiguous data-loss guard the triage mandates — the teardown's `delete_branch=ready_phase not in
  preserve_branches` (`runner.py:4730`) must never destroy the only validated copy after a block, independent
  of the transport choice below. This is the safety net: even if fix 2 misses an edge, no data is lost.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify — #300 fix 2: transport the staged plan artifact)
- **Modify** the non-real-exec `else` branch (`runner.py:4689-4709`, currently `integrate_phase_worktree`):
  before finalize, detect whether the child worktree carries **uncommitted** work (search for how the wave
  holds `handles[ready_phase]`; check `git status --porcelain` in `handle.worktree_path`, or reuse the
  `had_changes` signal from a transport call). When uncommitted plan work is present, transport it with
  `transfer_phase_worktree_dirty` (`runner.py:4666` / `phase_worktree_executor.py:306`) so the plan +
  `plans/manifest.json` reach the **main** working tree before `_finalize_phase_launch` resolves
  `find_plan_artifact` (`runner.py:3717`). Keep `integrate_phase_worktree` for children that *committed* their
  work (dry-run/simulated). Preserve the existing conflict handling (on `transfer.had_changes and not
  transfer.applied`, add to `preserve_branches`, exactly as `runner.py:4671-4688`). Reason: the committed-only
  merge silently drops staged plan artifacts; dirty-transport mirrors serial mode and lets the parent's
  ownership-gated closeout commit them.
- **Gate on closeout mode to avoid recreating the manual-closeout footgun** (`runner.py:1328-1338`): only
  dirty-transport plan artifacts when `closeout_mode in {"commit", "push"}`. Under `--closeout-mode manual`,
  do **not** transport-then-strand — instead add `ready_phase` to `preserve_branches` and surface a
  recoverable coordinator event (mirror `_append_coordinator_event`, `runner.py:4677-4688`) so the child branch
  is retained for manual adoption. Reason: under `manual` no closeout commits the transported dirt, so
  transporting would strand it on main exactly as the startup guard warns; preserving the branch is lossless.
  (Fix 1 already guarantees no deletion on the resulting block.)

### `phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py` (modify/add — #301 Defect 1 regression)
- **Add** `test_scheduler_honors_declared_lane_execute_kind_over_verify_body_heuristic`. Build a phase plan
  whose execution-policy declares `work_unit=lane_execute` for a writer lane whose **body contains a `Verify:`
  task** (so `detect_reducer_lane` returns `verification_reducer`) and non-empty `owned files`. Drive the
  **production** path — call `select_next_work_unit(repo, plan, phase)` (`runner.py:5343`) and/or
  `_launch_ready_lane_wave` (`runner.py:5155`) — and assert the dispatched `identity.kind == "lane_execute"`
  (and, for the wave, that `default_executor_for_work_unit(kind, scheduler_assigned=True) ==
  DEFAULT_LANE_EXECUTOR`). **Mutation that proves the bite:** on pre-fix `runner.py`, the inline ternary yields
  `phase_reducer` (the `Verify:` body trips `reducer_kind`), so the assertion FAILS; after the helper honors
  the declared kind it PASSES. Do NOT assert on a kind computed in the test body — read it off the
  `WorkUnitState`/assignment the production function returns.

### `phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py` (modify/add — #301 Defect 2 regression)
- **PRIMARY (the load-bearing bite) — drive the production `run_loop`→`runner.py:1462` wiring, NOT the
  primitive.** `dispatch_lock.py` already implements `caller_run_id` matching fully (`:121, :159-166, :206-207`),
  so a test that constructs `DispatchLock(..., caller_run_id="R")` for both holder and caller **passes on
  pre-fix main** — it never touches the defect (which is that `runner.py:1462` never *passes* `caller_run_id`).
  This is exactly the tautological-test class the repo has blocked PRs for. Instead add
  `test_run_loop_stamps_run_id_into_dispatch_lock`: invoke `run_loop` (or the minimal entry that reaches
  `runner.py:1462`) with `PHASE_LOOP_RUN_ID=R` in the child/subprocess env, hold/inspect the lock, and assert
  the **written lock file carries `run_id=R`** (and/or: a nested acquire presenting `caller_run_id=R` under the
  held lock re-enters without `DispatchLockContention`). **Mutation that proves the bite:** pre-fix,
  `runner.py:1462` passes no `caller_run_id`, so the lock file records **no** `run_id` (the write is gated on
  `caller_run_id` being present, `dispatch_lock.py:206-207`) → assertion FAILS; after threading `run_id` at
  `runner.py:1462` it is written → PASSES. Read the id off the lock file the production code wrote, never off a
  value constructed in the test body.
- **SUPPLEMENT (primitive + env unit tests, not the proof).** Add
  `test_nested_run_recognizes_own_lock_via_run_id_without_ancestry`: hold as
  `DispatchLock(repo, roadmap, caller_run_id="R")`, then from a context whose `os.getpid()` is **not** an
  ancestor (distinct/mock pid or a real `start_new_session` child) assert
  `DispatchLock(repo, roadmap, caller_run_id="R").acquire()` re-enters (`reentrant is True`) while
  `caller_run_id="OTHER"` still raises `DispatchLockContention`. And an env-propagation unit test:
  `child_executor_env(run_id="R")["PHASE_LOOP_RUN_ID"] == "R"`, and `child_executor_env()` (no run id) omits the
  key. These pin the primitive/propagation but do not, by themselves, prove the production wiring — the PRIMARY
  test does.

### `phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py` (modify/add — #300 regression)
- **Add** `test_concurrent_wave_preserves_and_adopts_staged_plan_artifact`. Drive `run_loop` with
  `--phase-scheduler concurrent` (model the existing tests in this module) and a worker whose planning turn
  leaves a **staged, uncommitted** plan artifact + `plans/manifest.json` in the child worktree and returns
  `terminal_status=planned`, rc 0. Assert BOTH: (a) after the wave, `find_plan_artifact(repo, phase, …)`
  (`runner.py:3717`) resolves the plan in the **main** worktree (fix 2 transported it) and the phase is **not**
  blocked with `planning_launch_missing_current_plan_artifact`; and (b) the child branch/worktree is **not
  deleted** while the phase is blocked (fix 1) — assert the branch still exists when finalize blocks. **Mutation
  that proves the bite:** on pre-fix `runner.py`, `integrate_phase_worktree` is a no-op on staged work → plan
  absent from main → finalize blocks → teardown deletes the branch, so both assertions FAIL; after fixes 1+2
  they PASS. Do NOT stage the plan into the main repo from the test body — the artifact must arrive via the
  production transport.
- **Add** `test_concurrent_manual_closeout_preserves_child_plan_branch_without_stranding`: same geometry but
  `--closeout-mode manual`; assert the child branch is **preserved** (not transported-and-stranded, not
  deleted) and a recoverable coordinator event is emitted. Mutation: pre-fix the branch is deleted; post-fix it
  is preserved.

## Dependencies / order
1. #301 Defect 1 (`runner.py` kind helper + both call sites). Independent; land first — smallest, most
   isolated.
2. #301 Defect 2 (`runner.py:1462` run_id + `harness_env_signatures.py` propagation). Independent of Defect 1;
   `dispatch_lock.py` already supports it.
3. #300 fix 1 (preserve-before-teardown) — land before fix 2; it is the standalone data-loss guard and makes
   fix 2 safe to iterate.
4. #300 fix 2 (staged-plan transport + closeout-mode gate).
5. Tests alongside each (a test must FAIL on the pre-fix tree and PASS after — verify by stashing the source
   edit and running the new test first).

Defects/fixes are orthogonal (kind vs. lock vs. transport), so they may land as separate commits in one PR;
sequence tests to prove each bite before its fix.

## Verification
From `phase-loop-runtime/`:
- Prove each bite pre-fix (must FAIL before the corresponding source edit, PASS after):
  - `PYTHONPATH=src:tests python3 -m pytest -q tests/test_phase_loop_lane_scheduler.py -k declared_lane_execute`
  - `PYTHONPATH=src:tests python3 -m pytest -q tests/test_dispatch_lock_reentrancy.py -k inherited_run_id`
  - `PYTHONPATH=src:tests python3 -m pytest -q tests/test_phase_loop_concurrent_phase_dispatch.py -k "staged_plan or manual_closeout"`
- Full default lane: `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"`
  (known pre-existing unrelated failure: `test_task_message_resolver::test_control_socket_...` reproduces on
  clean main — not caused by these changes).
- Model-id guard (no model-id surface touched; run for hygiene):
  `python3 phase-loop-runtime/scripts/check_model_id_sources.py`.
- Regression targets that must stay green (they exercise the touched primitives):
  `PYTHONPATH=src:tests python3 -m pytest -q tests/test_dispatch_lock_same_roadmap.py tests/test_dispatch_lock_cross_roadmap.py tests/test_dispatch_lock_helper.py tests/test_phase_worktree_executor.py tests/test_phase_loop_worktrees.py`.

## Acceptance criteria
- [ ] A plan lane that declares `work_unit=lane_execute` but has a `Verify:` task in its body dispatches as
      `lane_execute` (not `phase_reducer`) from both `select_next_work_unit` and `_launch_ready_lane_wave`; the
      new lane-scheduler test FAILS on pre-fix main and PASSES after.
- [ ] A nested phase-loop invocation that inherits `PHASE_LOOP_RUN_ID` re-enters its own outer DispatchLock
      (no `concurrent_dispatch`) even without PID ancestry, while a caller with a different/absent id still
      contends; `run_loop` writes the run id into the lock file; the new re-entrancy test FAILS pre-fix, PASSES
      after.
- [ ] Under `--phase-scheduler concurrent`, a planning worker's **staged** plan artifact reaches the parent
      worktree and the phase is not blocked as missing; the child branch is never deleted while a phase is
      blocked; the new concurrent-dispatch test FAILS pre-fix, PASSES after.
- [ ] Under `--phase-scheduler concurrent --closeout-mode manual`, the child plan branch is preserved (not
      stranded, not deleted) with a recoverable coordinator event.
- [ ] `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"` shows no new failures beyond
      the known `test_task_message_resolver::test_control_socket_...`.

## Out of scope / follow-up (state plainly; not required for closure)
- **#301 Expected #3 — parent skipping phase verification after a no-diff `concurrent_dispatch`.** Defect-2's
  fix removes the trigger (the executor no longer self-blocks, so it produces a diff and verification is
  relevant). A defensive guard that skips runner-owned phase verification when a work unit returns
  `concurrent_dispatch` with `dirty_paths=[]` is genuine defense-in-depth but requires tracing the exact
  verification-dispatch site and its own regression; recommend a **separate follow-up issue** rather than
  widening this cluster. Not planned here to keep the fix reviewable.
- **No skill-bundle change.** Contrary to the triage hand-off, the `concurrent_dispatch` refusal is entirely
  runtime (DispatchLock); the execute-phase skills are not involved. `regenerate_skills_bundle.py` /
  `sync_skills_bundle.py` are **not** run for this change.
- **Global `real_exec_integration` flag unification.** #300 fix 2 makes the concurrent path correct for staged
  plan artifacts without flipping the env flag, but the flag still conflates "child leaves dirty work" with
  "which transport." A follow-up could choose transport per-child from the child's actual worktree state
  (committed vs. dirty) rather than a global env flag, retiring the flag. Out of scope here.
