# Detailed plan: closeout / terminal integrity cluster (ah#298 + ah#294)

## Task

Two triage-grouped defects in the phase-loop runtime, both a species of "the runtime discards
trusted phase output":

- **ah#298** — a bounded `phase-loop resume` **repair child recursively launches another repair**
  (via nested `phase-loop resume`) instead of reconciling the trusted closeout; and when the
  operator interrupts the recursion, the interrupt **clobbers** a prior trusted
  `awaiting_phase_closeout` / verification `passed` terminal with
  `blocked` / `repeated_verification_failure`.
- **ah#294** — a **phase-authorized roadmap amendment** made during execute is not classifiable as
  phase-owned output (`_classify_dirty_paths` has no concept of it), so closeout fails
  `missing_phase_owned_dirty_paths`; goal-coverage separately flags the intended roadmap-hash change.

## Split recommendation (read first — explicit call)

**Ship ah#298 from this plan; SPLIT ah#294 into its own design-track issue + plan.** This document
therefore contains (Part A) an **implementation-ready** plan for ah#298 and (Part B) a
**design-contract** for ah#294 with a concrete recommendation to split.

Why split ah#294:
- It is a **design change**, not a bug fix. The runtime has **no** notion of an *authorized* client-repo
  roadmap amendment. Making one requires a *typed, authorized, recorded, closeout-recognizable* amendment
  contract that four subsystems must consume in agreement: `_classify_dirty_paths` (classify the roadmap
  file as phase-owned), `goal_coverage` (accept the amended roadmap hash as the new planning anchor),
  `reconcile` (the completion-invalidation invariant already reacts to roadmap-hash drift —
  `reconcile.py:1153-1189`, `_amendment_drift_fields`, `gold_record_amendment`), and the closeout
  commit/push boundary.
- It carries a **soundness hazard that ah#298 does not**: an executor must not be able to *self-authorize*
  an arbitrary roadmap rewrite to escape ownership/goal-coverage checks. Getting that authorization model
  right is the bulk of the work and is an open design question, not a code fix.
- There is **partial scaffolding but it does not fit**: a typed `SpecDeltaCloseout` with a
  `roadmap_amendment` decision literal already exists (`models.py:1042-1059`; literal at
  `models.py:276`), but its `SPEC_DELTA_TARGET_SURFACES` (`models.py:283-292`) are **fleet protocol/skill
  surfaces** (`shared/phase-loop/protocol.md`, `vendor/…`, `*/skills/**`) — **not** the client repo's
  roadmap (`plans/phase-plans-v*.md`). So the existing literal is prior art to build on, not a drop-in.
- Coupling a shippable, fail-closed integrity fix (ah#298) to an unresolved multi-subsystem design would
  make the combined change unreviewable and stall the fix.

Bundling them was the right *triage* call (same subsystem, same theme). For *implementation* they diverge:
ah#298 is a contained runtime guard + prompt hardening; ah#294 is a design increment. Part B specs the
contract so the split issue starts from a decided shape, not a blank page.

## Research summary (source-verified on `feat/fab-265-merge-queue-bound` @ `9540f91`)

Reproduces as filed. Both defect sites confirmed by reading source (not inferred):

**ah#298 — no lineage/depth guard exists.** `grep -rn "repair_depth|REPAIR_LINEAGE|PHASE_LOOP_REPAIR|repair_lineage"`
over `src/` returns **empty**. The only child-process env sentinel is `PHASE_LOOP_CHILD=1`
(`harness_env_signatures.py:35`, stamped in `child_executor_env`, `harness_env_signatures.py:194-205`),
which disambiguates "am I a phase-loop child" but carries **no repo/phase lineage** and cannot reject a
nested repair. The runner decides to repair at `runner.py:2311` (`launch_action = "repair"`, reached only
after `_build_repair_context`, `runner.py:2267`); nothing there consults any nested-repair signal.

**ah#298 — the recursion driver is the repair PROMPT (runtime-owned, not skills-src).** Triage assumed the
prompt leg lived in `skills-src/<harness>/…`. It does not: the repair-child prompt is built in
`prompts.py:84-153` (the `action == "repair"` branch of the prompt builder). Its "Allowed outcomes"
(`prompts.py:135-138`) say "leave the phase resume-ready" and never forbid running `phase-loop resume`/`run`;
a codex repair child, with the operator-facing phase-loop `SKILL.md` auto-loaded (which documents `resume`
and describes the runner launching bounded repair turns, `phase-loop/SKILL.md:155-175`), runs
`phase-loop resume` to "reconcile" — which re-enters a **fresh runner process** that sees the phase still
blocked/awaiting and launches **another** repair child. That is the P0→C1→P1→C2 recursion in the issue.

**ah#298 — the interrupt clobbers trusted state unconditionally.** `_launch_contract_blocker`
(`runner.py:7905-7941`) returns a `repeated_verification_failure` blocker on `result.interrupted`
(`runner.py:7932-7941`) with **no** check for whether the interrupted unit was a *repair coordinator that
made no repo changes*. Its caller (`runner.py:3497`) then, in the `if launch_contract_blocker:` branch
(`runner.py:3560-3619`), persists a `terminal_status="blocked"` summary and writes state — **superseding**
the prior trusted terminal. The prior trusted terminal **is still readable** at that site: the pre-launch
`snapshot` (carrying `snapshot.terminal_summary` and `snapshot.blocker_class`, e.g. used at
`runner.py:982/992`) is in scope, and `pre_launch_dirty_paths` is available from `prep`
(`runner.py:3460`). So a sound "preserve" fix has the inputs it needs at that site.

**ah#294 — the amended roadmap can never be phase-owned.** `_classify_dirty_paths` (`runner.py:8350-8471`)
classifies a dirty path as phase-owned only via `ownership.matches_dirty_output(path)` (`runner.py:8396`;
the amended roadmap is not in the phase's owned globs) or `is_sibling_phase_plan_doc` (`runner.py:8365`).
`is_sibling_phase_plan_doc` (`runner.py:845-864`) matches **only** `plans/phase-plan-<version>-<ALIAS>.md`
sibling *plan* docs — it explicitly requires the two-part `plans/phase-plan-…` name and rejects the roadmap
file itself (`plans/phase-plans-v*.md`). So the amended roadmap is neither → not phase-owned →
`phase_owned_dirty` false (`runner.py:8467`) → closeout blocks `missing_phase_owned_dirty_paths`.
`goal_coverage.check_goal_coverage` (`goal_coverage.py:152`; preflight at `runner.py:6165-6179`) separately
compares the plan's declared roadmap hash to the on-disk roadmap and reports the intended amendment as a
mismatch.

## Known-good pre-existing failure

`test_task_message_resolver::test_control_socket_...` fails on clean main; not caused by this work.

---

## Part A — ah#298 (implementation-ready)

Defects 1 and 2 are **complementary, not redundant** (state this in the PR): the lineage guard stops *this*
specific recursion at dispatch time; the preserve-terminal fix is the *general* safety net for **any**
interrupt during a no-op repair coordinator (including future recursion shapes the guard doesn't anticipate).
Ship both.

### A1 — Fail-closed nested-repair guard (primary: parent-written lease; fast-path: env marker)

**Design crux (the one failure mode a CR will probe): the signal must reach P1.** The recursion crosses two
different env hops: P0(runner)→C1(codex child) is the *inherited-env* hop that `PHASE_LOOP_CHILD` already
survives; but C1→P1 is C1 spawning a **sandboxed shell grandchild** that runs `phase-loop resume`. Env
survival across *that* hop is **not** demonstrated by existing `PHASE_LOOP_CHILD` usage (which is only ever
read inside C1's own process, `harness_env_signatures.py:175`). Resting a fail-closed integrity guard solely
on an unverified env hop is exactly the fail-open a review round flushes. Therefore:

- **Primary signal = a parent-written repair lease in `.phase-loop/`.** Before P0 launches the repair child,
  P0 writes a lease record (e.g. `.phase-loop/repair-active/<phase>.json`) naming `(repo, roadmap, phase,
  p0_pid, p0_run_dir, started_at)`. Any runner deciding to dispatch a repair for the same `(repo, phase)`
  first reads the lease; a **live** lease → refuse to dispatch a nested repair. The lease lives on disk, so
  it is visible to P1 regardless of whether env survived the C1→P1 hop.
- **Fast-path signal = env lineage marker.** Also stamp a lineage env var (e.g.
  `PHASE_LOOP_REPAIR_LINEAGE=<repo-id>:<phase>`) into the repair child's env. When it *does* survive, P1
  rejects without even reading disk. Belt-and-suspenders; never the sole guard.

**Lease lifecycle (this is the real design work — it is what makes "must NOT mask a legitimate FIRST
repair" hold):**
- **Acquire:** P0 writes the lease immediately before the repair-child launch (after `launch_action` is set
  to `"repair"`, `runner.py:2311`, and before `launch_with_spec`). A *first* repair sees no lease → proceeds,
  then writes it. Only the *nested* resume (P1) sees a live lease.
- **Release:** P0 removes the lease when it reconciles the repair child's terminal (success, blocked, or
  interrupt handling) — i.e. on every P0 exit path out of the repair dispatch. A *later, separate* legitimate
  repair invocation starts with no lease → allowed. This is what prevents the guard from wedging future
  repairs.
- **Staleness / crash safety:** the lease records `p0_pid` and `p0_run_dir`; a lease whose `p0_pid` is no
  longer alive (or whose run-dir is gone) is treated as stale and ignored/reclaimed, so a crashed P0 does not
  permanently block repair. Fail-closed means: when in doubt (lease present, liveness *unknown*), **refuse
  the nested repair and reconcile the trusted terminal** rather than recurse — refusing is the safe default
  because the trusted `awaiting_phase_closeout/passed` is preserved either way.

**What "refuse" does (must NOT recurse, must NOT clobber):** when the guard fires at P1, do **not** set
`launch_action="repair"`. Instead reconcile: re-emit / preserve the existing trusted terminal summary for the
phase and return a typed non-recursive outcome (e.g. a `nested_repair_refused` metadata marker on a
reconcile event). P1 must exit having *changed nothing* about the trusted terminal.

**Changes:**

- `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)
  - **Add** a pure, directly-callable predicate `_repair_dispatch_blocked(repo, roadmap, phase, *, env=os.environ) -> str | None`
    (search for the `launch_action = "repair"` assignment, `runner.py:2311`, and place the helper near the
    repair-context helpers, e.g. above `_build_repair_context`, `runner.py:6862`). Returns a typed reason
    string when a live lease OR a matching env lineage marker indicates we are already inside a repair for
    the same `(repo, phase)`; `None` otherwise. **Reason:** extracting the predicate is required so the
    regression test drives the **production** decision function, not a reconstruction (repo lesson: a guard's
    test must reuse the runtime func; recent PR blocked for tautological tests).
  - **Add** lease read/write/release helpers (`_repair_lease_path`, `_write_repair_lease`,
    `_read_live_repair_lease`, `_release_repair_lease`) operating on `.phase-loop/repair-active/<phase>.json`,
    with pid/run-dir liveness for staleness. **Reason:** on-disk lease is the fail-closed primary that does
    not depend on the C1→P1 env hop.
  - **Modify** the repair-dispatch decision (at/around `runner.py:2311`): before committing
    `launch_action="repair"`, call `_repair_dispatch_blocked(...)`; if it returns a reason, take the
    **reconcile-not-recurse** path (preserve trusted terminal, emit a `nested_repair_refused` event, break)
    instead of dispatching. If it proceeds, `_write_repair_lease(...)` before launch and
    `_release_repair_lease(...)` on every repair-dispatch exit path. **Reason:** this is the fail-closed
    fire-site; P1 is exactly the runner that reaches here while a P0 lease is live.
- `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py` (modify)
  - **Add** a `PHASE_LOOP_REPAIR_LINEAGE_ENV = "PHASE_LOOP_REPAIR_LINEAGE"` constant next to
    `PHASE_LOOP_CHILD_ENV` (`harness_env_signatures.py:35`), and extend `child_executor_env`
    (`harness_env_signatures.py:194-205`) with an optional lineage argument stamped when launching a repair
    child. **Reason:** fast-path signal; keep it additive so non-repair child env stays byte-identical
    (guard the new stamp behind the caller passing a lineage value).

### A2 — Preserve trusted terminal on interrupt of a no-op repair coordinator

**Sound predicate (byte-level, the advisor's negative-test bar):** preserve the prior trusted terminal ONLY
when **all** hold: (a) `launch_action == "repair"`; (b) the launch ended in an interrupt/cleanup-only blocker
(`result.interrupted`, and by extension the `stalled`/`timed_out`/cleanup blocker paths that also mean "the
coordinator was killed, not that verification failed"); (c) the repair coordinator made **no repo changes** —
post-launch worktree dirty set **equals** the pre-launch dirty set **AND** `HEAD` is unchanged; (d) a prior
trusted terminal exists in the pre-launch `snapshot` with `terminal_status == "awaiting_phase_closeout"` (or
otherwise non-blocked) and `verification_status == "passed"`. If any fails → keep the existing `blocked`
behavior. The `git add` staging index the recursion left intact (issue: "staged application index remained
intact") means the trusted terminal's staged boundary is still valid to preserve.

**Changes:**

- `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)
  - **Add** a pure predicate
    `_preserve_trusted_terminal_on_repair_interrupt(launch_action, result, prior_terminal, pre_launch_dirty, post_launch_dirty, head_before, head_after) -> dict | None`
    (place near `_launch_contract_blocker`, `runner.py:7905`). Returns the prior trusted terminal dict to
    preserve when the A2 predicate holds, else `None`. **Reason:** pure + production-called so the test drives
    it directly (both a positive and a **negative** case).
  - **Capture `HEAD` before launch** in the dispatch prep (search for where `pre_launch_dirty_paths` is set
    on `prep`, consumed at `runner.py:3460`) so `head_before` is threaded to the site. **Reason:** the "no
    repo changes" check must be byte-sound (dirty-set equality alone can't detect a commit; HEAD equality
    catches it).
  - **Modify** the `if launch_contract_blocker:` branch (`runner.py:3560-3619`): before persisting the
    `blocked` terminal, compute `post_launch_dirty = _dirty_paths(repo)` and `head_after`, then call
    `_preserve_trusted_terminal_on_repair_interrupt(...)` with `prior_terminal=snapshot.terminal_summary`.
    If it returns a terminal, **re-persist / retain that trusted terminal** (and emit a
    `repair_interrupt_terminal_preserved` metadata marker) instead of writing the `blocked` summary; leave
    classifications/state on the trusted terminal. Otherwise keep current behavior verbatim. **Reason:** this
    is the exact superseding site; the fix must be a *narrow* guard in front of the existing clobber, not a
    rewrite of the blocked path.

### A3 — Prompt hardening (defense-in-depth, runtime-owned)

The prompt change is **advisory**; the A1 lease guard is the **enforcement**. Do not test the prompt text
(grepping the prompt for a phrase is the tautology trap the recent PR was blocked for).

- `phase-loop-runtime/src/phase_loop_runtime/prompts.py` (modify)
  - **Modify** the `action == "repair"` "Allowed outcomes" block (`prompts.py:135-138`): add an explicit
    instruction that a repair child must **not** invoke `phase-loop resume`/`run`/`repair`; it must emit the
    shared automation closeout for the parent runner to reconcile (this aligns with the already-present
    checklist item 8, `prompts.py:130-131`, "emit a valid shared automation closeout so the parent runner can
    reconcile"). **Reason:** removes the *behavioral* driver of the recursion at the source, so the lease
    guard is a backstop rather than the everyday path.
- **skills-src leg — verify before doing.** The operator-facing `phase-loop/SKILL.md:155-175` documents the
  runner launching bounded repair turns and mentions `resume`, but does **not** instruct a repair *child* to
  run `resume`. Recommendation: **do not** touch skills-src unless, at implementation time, you confirm a
  generated `SKILL.md` copy a repair child auto-loads actually instructs `resume`. If it does: edit the
  **neutral base** (`phase-loop-skills/…`, base = codex), then
  `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py`, THEN sync — never hand-edit generated
  copies. State the decision in the PR either way.

### A — Regression tests (each drives the production path; each bites before the fix)

Place in an **UNMARKED** module so the default CI lane (`-m "not dotfiles_integration"`) runs them:
`phase-loop-runtime/tests/test_phase_loop_repair_recursion_298.py` (create).

1. **`test_nested_repair_dispatch_is_refused_when_lease_live`** — drive `_repair_dispatch_blocked` (the
   production predicate) with a live lease written for `(repo, phase)`; assert it returns a non-`None`
   `nested_repair_refused` reason. **Mutation that proves it bites:** on pre-fix main the function does not
   exist / dispatch has no guard, so a test that asserts the runner takes the reconcile path for a nested
   resume FAILS (it recurses); after A1 it PASSES. (Prefer an integration-style test that runs a second
   dispatch while a lease is present and asserts **no** second repair `launch_action` and a
   `nested_repair_refused` event, so the bite is on real dispatch, not just the predicate.)
2. **`test_first_repair_is_not_blocked`** (negative/anti-mask) — with **no** lease and no lineage env,
   `_repair_dispatch_blocked` returns `None` and a first repair dispatches normally. **Proves** the guard does
   not mask a legitimate first repair. Also assert a lease is written on dispatch and released on exit.
3. **`test_interrupted_repair_noop_preserves_trusted_terminal`** (positive) — construct a `LaunchResult`
   with `interrupted=True` for `launch_action="repair"`, `pre==post` dirty set, `head_before==head_after`,
   and a `snapshot.terminal_summary` of `awaiting_phase_closeout`/`passed`; assert
   `_preserve_trusted_terminal_on_repair_interrupt` returns that terminal AND (integration) the persisted
   state retains `awaiting_phase_closeout`, not `blocked`. **Mutation that proves it bites:** on pre-fix main
   `_launch_contract_blocker` returns `repeated_verification_failure` and the blocked terminal is persisted —
   the assertion that the trusted terminal survives FAILS before A2, PASSES after.
4. **`test_interrupted_repair_that_changed_repo_still_blocks`** (negative/soundness) — same but with
   `post != pre` dirty **or** `head_after != head_before`; assert the predicate returns `None` and the
   `blocked` terminal is still written. **Proves** the fix cannot silently preserve a stale "passed" over real
   divergence.

## Part B — ah#294 (design contract; RECOMMEND SPLIT into its own issue + plan)

Do **not** implement from this document. This section states the contract so the split issue starts decided.

**The gap:** there is no *typed, authorized, closeout-recognizable* client-repo roadmap amendment. A phase
that legitimately edits its roadmap (e.g. a SPIKE amending a downstream FREEZE contract) produces a dirty
`plans/phase-plans-v*.md` that (a) `_classify_dirty_paths` cannot call phase-owned and (b) goal-coverage
flags as a hash mismatch.

**Contract to design (state each in the split issue):**

1. **Authorization — who may amend, and how it is bounded (the soundness core).** An executor must **not**
   self-authorize an arbitrary roadmap rewrite to escape ownership/goal-coverage. Options to weigh:
   the phase plan must *declare* an amendment intent (a plan-frontmatter field naming the roadmap and the
   permitted amendment scope, e.g. which phase blocks/aliases may change), so the runtime authorizes only
   the *declared* surface; and/or the amendment must be limited to *downstream, not-yet-started* phase
   blocks (never the current phase's own completion-bearing block, which the completion-invalidation
   invariant, `reconcile.py:1153-1189`, correctly distrusts).
2. **Typed record — reuse, don't reinvent.** Extend the existing `SpecDeltaCloseout`
   (`models.py:1042-1059`) `roadmap_amendment` decision (`models.py:276`) to cover the **client-repo**
   roadmap: today `SPEC_DELTA_TARGET_SURFACES` (`models.py:283-292`) are fleet protocol/skill surfaces, so
   either broaden the accepted target surfaces to include the client roadmap or add a sibling
   `roadmap_amendment` record whose `target_surfaces`/`evidence_paths` name the exact roadmap file + amended
   blocks. Decide which in the split issue.
3. **Classification consumption.** `_classify_dirty_paths` (`runner.py:8350-8471`) must recognize the
   roadmap file as phase-owned **only when** a valid authorized-amendment record for this phase names it —
   analogous to, but distinct from, `is_sibling_phase_plan_doc` (`runner.py:845-864`, which is scoped to
   `plans/phase-plan-…` sibling plans and must stay so). Thread the amendment record into the classifier the
   same way `terminal_summary` is threaded today.
4. **Planning-anchor consumption.** `goal_coverage.check_goal_coverage` (`goal_coverage.py:152`; preflight
   `runner.py:6165-6179`) must accept the amended roadmap hash as the new anchor when an authorized
   amendment record is present, rather than reporting a mismatch — the new hash becomes the downstream
   planning ground truth.
5. **Reconcile consumption.** Confirm interaction with `_amendment_drift_fields` /
   `gold_record_amendment` (`reconcile.py:1153-1189`): an *authorized* amendment should route through a
   recognized path, not surface as an undifferentiated drift warning.
6. **Closeout.** The verified staged boundary (artifact + authorized roadmap change) commits/pushes as one
   phase-owned unit; no `missing_phase_owned_dirty_paths`.

**ah#294 regression bar (for the split plan):** a test driving `_classify_dirty_paths` with an authorized
amendment record present asserts the roadmap path lands in `phase_owned_dirty_paths` (FAILS today: it lands
nowhere / unowned); plus a **negative** test that an *unauthorized* roadmap edit (no record, or outside the
declared scope) still does **not** become phase-owned — this is the self-authorization guard and is
mandatory.

## Dependencies / order (Part A)

1. `harness_env_signatures.py` lineage constant + `child_executor_env` optional stamp (leaf; additive).
2. `runner.py` A1: lease helpers + `_repair_dispatch_blocked` predicate + wire into repair-dispatch
   (write/refuse/release).
3. `runner.py` A2: `head_before` capture in prep + `_preserve_trusted_terminal_on_repair_interrupt`
   predicate + wire into the `if launch_contract_blocker:` branch.
4. `prompts.py` A3 wording.
5. New regression module `test_phase_loop_repair_recursion_298.py` (last; must FAIL on pre-fix main per the
   stated mutations, PASS after).

## Verification (from `phase-loop-runtime/`)

- Prove the bite (pre-fix): `PYTHONPATH=src:tests python3 -m pytest -q tests/test_phase_loop_repair_recursion_298.py`
  → the two positive tests FAIL before their respective fixes, PASS after; the two negative tests must pass
  both before and after (they assert unchanged safe behavior) — confirm by staging fixes independently.
- Default lane: `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"`
  (known unrelated pre-existing failure: `test_task_message_resolver::test_control_socket_...`).
- Repair/closeout neighbors (run to confirm no regression):
  `PYTHONPATH=src:tests python3 -m pytest -q tests/test_phase_loop_repair_precondition_planned_closeout.py tests/test_phase_loop_dirty_path_classify_phase_owned_tests.py tests/test_closeout_convergence_fixes.py tests/test_launcher_liveness.py`.
- Model-id guard (hygiene): `python3 phase-loop-runtime/scripts/check_model_id_sources.py`.
- If the A3 skills-src leg is taken: `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py` then
  the bundle parity/drift check, and confirm generated copies match the neutral base.

## Acceptance criteria (Part A / ah#298)

- [ ] A live parent repair lease (or matching lineage env) makes a nested `phase-loop resume` **refuse** to
      dispatch a second repair and reconcile the trusted terminal; a **first** repair with no lease is not
      blocked (both proven by tests driving `_repair_dispatch_blocked` / real dispatch).
- [ ] An **interrupted repair coordinator that made no repo changes** (dirty-set unchanged AND HEAD
      unchanged) **preserves** the prior `awaiting_phase_closeout`/`passed` terminal instead of writing
      `blocked`/`repeated_verification_failure`; an interrupted repair that **did** change the repo still
      blocks (negative test passes).
- [ ] The repair prompt (`prompts.py`) instructs repair children to emit the shared closeout, not to run
      `phase-loop resume`/`run`; no test asserts on prompt text.
- [ ] `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"` shows no new failures beyond
      the known `test_task_message_resolver::test_control_socket_...`.
- [ ] ah#294 is filed as a separate design-track issue referencing Part B; this PR does not touch
      `_classify_dirty_paths` / `goal_coverage`.

---

## CR AMENDMENT — 2026-07-26 (codex DISAGREE, grok PARTIALLY AGREE)

**Part A is NOT executable as written.** Both legs endorse SPLITTING #294 into a separate
authorization-design track, and endorse Part A as the right size for one PR. The
following are normative.

### B1 (BLOCKING, both legs independently) — A2 guards the WRONG branch
Real interrupts return a NONZERO return code, so `result.failed` (`runner.py:3570`)
persists `blocked` BEFORE the proposed `if launch_contract_blocker` guard
(`runner.py:3632`) is ever reached. Followed literally, the fix does nothing.
**Required:** factor ONE shared "maybe preserve prior trusted terminal instead of writing
blocked" helper and call it from BOTH clobber sites (`if result.failed:` AND
`if launch_contract_blocker:`), before any blocked-terminal persist.
**Required test:** a realistic interrupted `LaunchResult` with `interrupted=True` AND a
non-zero returncode (e.g. `-15`); assert persisted state stays
`awaiting_phase_closeout`/`passed`. Same shape for the negative case.
Also thread `head_before` on `_DispatchPrep` beside `pre_launch_dirty_paths`.

### B2 (BLOCKING) — the "byte-level no-change proof" is UNSOUND
`_dirty_paths` (`runner.py:8362`) records only path NAMES and converts probe failure to
`[]` (`except Exception: return []` — verified verbatim). A repair can modify or restage
an ALREADY-dirty path while preserving both the path set and HEAD, so stale `passed`
evidence survives. A failed git probe also reads as CLEAN.
**Required:** a fail-closed content/index fingerprint, a same-path-content mutation test,
and NEVER preserve when `process_alive_after_cleanup` is true.

### B3 (BLOCKING) — the lineage marker never reaches production spawning
`launch_with_spec` (`launcher.py:1944`) supplies no lineage to `launch`, and `launch`
(`launcher.py:2259`) calls `child_executor_env()` without one. Changing
`harness_env_signatures.py` alone CANNOT satisfy the acceptance criterion.
**Required:** include the launcher seam; add a test proving the actual executor
subprocess receives the marker.

### B4 (BLOCKING) — lease identity is collision-prone
The proposed lease file is keyed only by phase, and the env marker only by repo+phase,
while repair identity includes the roadmap. Dispatch locks are explicitly roadmap-scoped
(`dispatch_lock.py:235`). Two roadmaps sharing an alias can overwrite/delete each other's
lease or falsely block a legitimate first repair.
**Required:** key BOTH signals by canonical repo+roadmap+phase; make release
ownership-token-safe; add a cross-roadmap regression test. Wrap lease acquisition in
`try`/`finally` — a missed release on a live P0 masks later repairs.

### B5 (BLOCKING, mine) — `_classify_dirty_paths` call sites are unenumerated
The #294 fix is "thread the amendment record into the classifier the same way
`terminal_summary` is threaded" — a SIGNATURE change. `_classify_dirty_paths` has **8**
call sites in runner.py (4269, 4309, 4336, 4362, 4406, 7018, 7064, 10367; def 8482) and
the plan enumerates NONE. This is the repo's most frequent defect class.
**Required (on the #294 split):** enumerate all 8 and add a test that fails if any one is
left unthreaded.

### Endorsed as written
A3 prompt hardening is correctly located in `prompts.py` (runtime-owned), not skills-src;
"verify before editing skills" is right; do NOT test prompt text. Repair dispatch has a
single assignment site. Part B stays design-only, out of the PR.

### Anchor re-grounding
DRIFTED: `_launch_contract_blocker` call **3569**, def **8037** (plan cited 3717);
`_classify_dirty_paths` def **8482** (plan cited 8350-8471). Re-locate by symbol.
