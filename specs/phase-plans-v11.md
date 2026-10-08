# Phase roadmap v11 — Fast Loop First, Then Finish v10

> **Status (2026-10-08): ACTIVE — created this date, nothing executed yet.**
> Completion is recorded in the ledger (`plans/manifest.json`), not by ticking these boxes.

## Context

v10 (`specs/phase-plans-v10.md`, created 2026-07-29) closed six phases in its first four weeks —
LEGIBLE, CONFORM, PROOFGATE, GOVLEAN, FABPUB, FABREADMIT — and none in the six weeks after.
Over that second stretch, amendments appended six phases (13–18), the critical path grew from 8 to 10,
and the document grew to about 36,000 words. The phases that would speed up the agents
building this repo (leg reaping, vendor fallback, autonomous rulings) sat in waves 5–6, behind
the governance chain they would accelerate.

Measured on 2026-10-08, the dogfooding loop is not slow at merging (median 2.2 h from open
to merge). It is slow everywhere around the merge:

- `main` is red after about 27% of landings. Most red runs come from test classes that PR CI
  skips (py3.11/3.12, Gate A, the chronology node, the merge commit); the rest are flakes.
- CI on `main` takes 70–116 min. On a team host the full suite is unusable: hundreds of errors
  reproduce on clean `main`, mostly from root-owned `/mnt/workspace`, `TMPDIR` placement and
  nested user namespaces, with no marker to separate them.
- Review rounds do not converge: one PR is past round 16, and 36 open issues were spawned by
  review rounds. The round cap halts instead of descoping, and findings need not cite a goal.
- Phases run one at a time. The phase scheduler is off by policy; when on, it is
  wave-barriered, and one shared file serializes a whole wave. `panel_invoker.py` (about 14,000
  lines) is claimed by eight phases.
- 259 admitted agent reflections (agent-harness#1301) report the same friction from inside
  runs: the closeout audit blocks on ignored files a run did not create; a `failed` plan cannot
  record a later result; the plan validator rejects its own skill's template; skills cannot
  import the runtime from system `python3`.

Execution is also pinned to one author vendor per phase, a v10 rule that kept both schedulers
off, and the review gate excludes every author vendor from the reviewer pool, so routing work
across vendors would leave no reviewer.

v11 therefore does two things, in this order: make the loop fast and parallel, then finish v10's
unfinished phases on that faster loop. Unfinished v10 phases are carried with their aliases and
goal IDs unchanged.

## Assumptions (fail-loud if wrong)

1. The six v10 phases recorded `completed` in the ledger are delivered; v11 does not re-verify
   them. If a regression is found, it is filed as an issue against the owning v11 phase, not
   reopened as a v10 phase.
2. Every in-flight v10 branch is listed in `spikes/v11-transition/inventory-2026-10-08.md` and has a copy on `origin`.
   Work found later that is not listed is routed through an issue, not a new phase.
3. `skills-src/` is the canonical skill source and the generated bundles follow it
   (`docs/phase-loop/skills-canonical-source.md`).
4. A shared team host — root-owned `/mnt/workspace`, `TMPDIR` under `/mnt/workspace/users/<u>`,
   no nested user namespaces — is a supported development and test environment.
5. GitHub merge queues are available to this repository. If not, TESTLOOP substitutes a
   required post-merge lane that blocks the next landing; the goal does not change.

## External Inputs

Pinned inputs this roadmap consumes. Never pin this roadmap's own outputs.

- **V10** — `specs/phase-plans-v10.md` as of `origin/main` commit `9eb77a3d`, before its
  supersession banner. Every carried `EC-<ALIAS>-N` and `IF-0-<ALIAS>-N` below means the text
  of that ID in V10. Its `## Execution Notes` amendments and rulings are inputs only where a
  carried phase below names them.
- **Handoffs** — `spikes/pstack-comparison/handoffs/00-SHARED-CONTEXT.md` through
  `05-pstack-alignment.md`.

## Non-Goals

- Re-verifying or re-planning delivered v10 phases.
- The jevdrill integration and native-Windows work (uncommitted on dev0). It is a separate
  initiative with its own roadmap if it proceeds.
- Adopting the PStack programme wholesale. REFLOOP admits individual items through its gates.
- New cross-repo convergence features beyond what INTEG and RELEASE carry.
- Binding phases, lanes or jobs to Consiliency/spec frontier subtrees (spec diff plus frontier-scoped parity as the unit of work). That needs spec-side primitives that do not exist yet (subgraph endpoints, authoring tools) and is a joint follow-on roadmap; ROUTE's spec scope is the hook it will use.
- Restating or re-numbering any carried goal. A carried goal changes only by an explicit
  retirement-and-replacement recorded in its phase, never by paraphrase.

## Cross-Cutting Principles

1. **`Depends on` is the only ordering.** No prose edge, ruling, or dispatch hold may order
   phases. A ruling that changes order lands as an amendment to `Depends on`.
2. **Independent phases do not share files.** Two phases with no DAG path between them must
   have disjoint Key files. Where unavoidable, the overlap is listed under Execution Notes and
   the scheduler excludes the pair from running together; it does not serialize the wave.
   PARSCHED makes this check mechanical.
3. **Loop first.** A phase that shortens plan → execute → review → land for this repo is
   scheduled ahead of governance or client-facing work unless a real interface dependency
   says otherwise.
4. **Reference goals, never restate them.** Carried phases list their open goal IDs and point
   at V10. Line numbers inside V10 goal text are historical; each phase plan re-derives
   current locations.
5. **Pin inputs, never outputs.** This roadmap names no shipped version, future commit,
   commit count, or plan digest of its own work. Release bookkeeping does not edit it.
6. **Tests first, content-bound.** Every new phase's `EC-<ALIAS>-0` is a content-bound TDD
   receipt per IF-0-GOVLEAN-1 (delivered). A carried phase keeps its V10 `EC-<ALIAS>-0`.
7. **Bounded review.** From REVBOUND's landing on, a finding blocks only if it cites a goal ID,
   a contract, or a failing test, and a review that reaches its round cap descopes instead of
   halting.
8. **Spec-protocol compatibility.** Contracts that other repos copy or consume (`spec_delta_closeout`, phase and plan formats) change only by a new version, never in place. Anything keyed to code entities uses Consiliency/spec's node `name` or idmodel `logical_id`, never treesitter-chunker ids.
9. **Size.** Keep each phase section short; long contracts go in referenced artifacts. A phase
   plan that grows past the plan-size rule (agent-harness#1302) splits rather than amends.

## Absorbed work

**v10 phases.** v10 is superseded by this roadmap; its delivered phases stay recorded in the
ledger.

| v10 phase | Disposition in v11 |
|---|---|
| LEGIBLE, CONFORM, PROOFGATE, GOVLEAN, FABPUB, FABREADMIT | Delivered (ledger `completed`). Not carried. |
| PRESROUTE | Carried. All goals met in code; only EC-PRESROUTE-0 (receipt drift) is open. |
| HARDEN, SCHED, RUNTIME, EXECFIND, REVIEWTRUTH, PANEL | Carried, partly delivered. Open goals listed per phase. |
| LEGLIFE, RESIDUAL, INTEG, RELEASE, RATIFY, GOVSETUP | Carried, not started (RESIDUAL has its RED tests on main). |

**In-flight work and open issues.** Which pull request, branch and issue belongs to which v11
phase is recorded in `spikes/v11-transition/inventory-2026-10-08.md`. That file is a snapshot and
is not amended as work moves; the ledger and the phase plans are the live record.

## Top Interface-Freeze Gates

- **IF-0-TESTLOOP-1** — the host-capability pytest markers (`requires_nested_userns`,
  `network`) and the single `phase_loop_runtime.runtime_paths` worktree-root resolver that
  tests and production share.
- **IF-0-LOOPFIX-1** — `phase-loop validate-plan <path>`: same checks as the plan-phase
  validator, exit codes 0 / 1 / 2 (ok / findings / cannot evaluate), runnable from any
  interpreter on `PATH`.
- **IF-0-LOOPFIX-2** — the plan-manifest successor transition: `failed → superseded` carrying
  `successor_plan`, with `superseded` terminal and outside the in-flight set.
- **IF-0-REVBOUND-1** — `ReviewFinding.cites: tuple[str, ...]` (goal ID, contract, or test node
  ID) and the rule that an empty `cites` is non-blocking.
- **IF-0-REVBOUND-2** — the per-PR review-round ledger record (`review_round.v1`): PR, head,
  round number, cap, outcome (`converged | descoped | halted`).
- **IF-0-PARSCHED-1** — readiness-driven dispatch: a phase is dispatchable when its `Depends on`
  set is complete and it shares no owned path with a running phase.
- **IF-0-ROUTE-1** — the router interface: `route(work_unit) -> RouteDecision(executor, model, effort, fallbacks, reason)`, registered once and consulted by every dispatch path. `work_unit` carries an optional spec scope `{level, kind, name}` from Consiliency/spec's desired-state graph.
- **IF-0-ROUTE-2** — president selection: primary is the frontier model of the vendor opposite the phase's top-level model; fallback order and the recorded fallback field on the ruling.
- **IF-0-PANELSPLIT-1** — the `phase_loop_runtime.panel` package module map; every public and
  monkeypatched name stays importable from `phase_loop_runtime.panel_invoker`.
- Carried: IF-0-REVIEWTRUTH-1, IF-0-REVIEWTRUTH-2, IF-0-REVIEWTRUTH-3, IF-0-PRESROUTE-1,
  IF-0-EXECFIND-1, IF-0-RATIFY-1, IF-0-GOVSETUP-1, IF-0-PANEL-1 — as defined in V10.

## Phases


### Phase 0 — Trustworthy, Fast Test Signal (TESTLOOP)

**Objective**
Make a green PR mean a green `main`, and make the full suite usable on a team host.

**Exit criteria**
- [ ] EC-TESTLOOP-0 — Content-bound TDD receipt for this phase's tests, recorded before production changes.
- [ ] EC-TESTLOOP-1 — PR CI fails on a SyntaxWarning-as-error compile of `phase-loop-runtime/src` under the newest supported Python; falsified by reintroducing an invalid escape sequence and seeing PR CI pass.
- [ ] EC-TESTLOOP-2 — Landings go through a merge-queue lane that runs the push matrix (all supported Pythons, Gate A) on the merged tree; falsified by a change that breaks only py3.12 or Gate A reaching `main` through the queue.
- [ ] EC-TESTLOOP-3 — The chronology node runs on PRs whose diff can move it and nightly otherwise, with a recorded evidence witness; falsified by a chronology-moving diff that skips it.
- [ ] EC-TESTLOOP-4 — On a clean `main` checkout on a team host, the full suite reports 0 failures and 0 errors; every host-dependent skip names its marker; falsified by any unmarked host failure.
- [ ] EC-TESTLOOP-5 — Production worktree-root resolution (`runtime_paths`) and the agy canary workspace root use the team-host-aware resolver; falsified by a lane run on a host whose `/mnt/workspace/worktrees` is root-owned failing to create its worktree.
- [ ] EC-TESTLOOP-6 — Real-network tests are marked and excluded from hosted lanes; falsified by a hosted run failing on DNS.

**Scope notes**
- Decompose into 3 disjoint lanes: lane A CI workflows and `ci/` (EC-1..3); lane B markers, `conftest.py` probes and test fixtures (EC-4, EC-6); lane C production path resolution (EC-5). Lane B publishes IF-0-TESTLOOP-1 on day 1.
- Reuse the existing team-host probe in `verification_evidence.py` (`_mutation_worktree_parent`) rather than writing a new one.
- Track red-flip causes on agent-harness#766; the phase is done when the criteria hold, not when a red-free streak is observed.

**Non-goals**
- Faster individual tests or a CI hardware change.

**Key files**
- `.github/workflows/test.yml`
- `ci/chronology-scope.sh`
- `phase-loop-runtime/pyproject.toml`
- `phase-loop-runtime/tests/conftest.py`
- `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_canary_evidence.py`

**Depends on**
- (none)

**Produces**
- IF-0-TESTLOOP-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 1 — Closeout, Lifecycle and Plan-Validation Friction (LOOPFIX)

**Objective**
Remove the four closeout and planning failures agents hit most often, by mechanism rather than skill text.

**Exit criteria**
- [ ] EC-LOOPFIX-0 — Content-bound TDD receipt for this phase's tests, recorded before production changes.
- [ ] EC-LOOPFIX-1 — The closeout audit ignores ignored-output paths that existed unchanged before the phase started; falsified by a worktree with a pre-existing ignored directory failing closeout.
- [ ] EC-LOOPFIX-2 — A `failed` plan can be succeeded by a new plan through IF-0-LOOPFIX-2 without fabricating a transition; falsified by a resumed run unable to record its result.
- [ ] EC-LOOPFIX-3 — `phase-loop validate-plan` exists (IF-0-LOOPFIX-1) and every skill calls it instead of `python3 -m phase_loop_runtime…`; falsified by a skill instruction that imports the runtime from system `python3`.
- [ ] EC-LOOPFIX-4 — The plan-phase template in `skills-src/` passes `phase-loop validate-plan`, and the validator accepts every lane grammar the runtime parser accepts (the parser is not narrowed); a regression corpus includes downstream repos' committed plans (Consiliency/spec) and legacy roadmaps without goal IDs; falsified by the shipped template or a corpus plan producing a structural error the parser does not.
- [ ] EC-LOOPFIX-5 — The worktree sweep keeps a recently active worktree, branch deletion checks the merged head, and lane cleanup has `--dry-run` (agent-harness#1354); falsified by a negative-control test that reaches each removal path.

**Scope notes**
- Decompose into 4 disjoint lanes: lane A closeout classifier (EC-1); lane B plan manifest (EC-2); lane C validator, CLI verb and plan-phase skill (EC-3, EC-4); lane D worktree scripts (EC-5). Lane C owns `cli.py` for this phase.
- Regenerate bundles after `skills-src/` edits; one source edit fans out to the generated copies.

**Non-goals**
- Rewording other skills (REFLOOP).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/closeout_classifier.py`
- `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`
- `skills-src/*/*-plan-phase/SKILL.md`
- `skills-src/claude/claude-execute-phase/scripts/sweep_stale_worktrees.sh`

**Depends on**
- (none)

**Produces**
- IF-0-LOOPFIX-1
- IF-0-LOOPFIX-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 2 — Bounded Review Loop (REVBOUND)

**Objective**
Make review rounds converge: findings that block must cite something, rounds are counted per PR, and the cap descopes instead of halting.

**Exit criteria**
- [ ] EC-REVBOUND-0 — Content-bound TDD receipt for this phase's tests, recorded before production changes.
- [ ] EC-REVBOUND-1 — A finding with empty `cites` (IF-0-REVBOUND-1) is recorded non-blocking; falsified by an uncited finding blocking a landing.
- [ ] EC-REVBOUND-2 — Every governed review writes a `review_round.v1` record (IF-0-REVBOUND-2), and a board run past the declared cap is refused; falsified by round N+1 running past the cap.
- [ ] EC-REVBOUND-3 — At the cap, unresolved findings are filed as qualified issues and the PR proceeds on its cited, resolved findings (`descoped`); falsified by a capped run that halts with no issues filed, or descopes a cited, unresolved blocker.
- [ ] EC-REVBOUND-4 — A follow-up round reviews only the delta and re-seats only dissenting seats on the non-FAB path; falsified by a full re-review after a one-file fix.

**Scope notes**
- Decompose into 2 lanes: lane A finding citation and round ledger (EC-1, EC-2), which publishes IF-0-REVBOUND-1 and -2 on day 1; lane B descope and delta review (EC-3, EC-4).
- Cited, unresolved findings still block; descoping never drops a cited blocker.

**Non-goals**
- Changing seat composition or vendor fallback (PANEL).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`
- `phase-loop-runtime/src/phase_loop_runtime/closeout_validators.py`
- `phase-loop-runtime/src/phase_loop_runtime/review_rounds.py`

**Depends on**
- (none)

**Produces**
- IF-0-REVBOUND-1
- IF-0-REVBOUND-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 3 — Readiness-Driven Concurrent Phase Dispatch (PARSCHED)

**Objective**
Let phase-loop run every ready phase at once, excluding only pairs that share files.

**Exit criteria**
- [ ] EC-PARSCHED-0 — Content-bound TDD receipt for this phase's tests, recorded before production changes.
- [ ] EC-PARSCHED-1 — With `--phase-scheduler concurrent`, a phase starts within one scheduler tick after its last dependency completes, without waiting for the rest of its wave; falsified by a ready phase idle behind an unrelated running phase.
- [ ] EC-PARSCHED-2 — An ownership overlap excludes only the overlapping pair; falsified by one overlap serializing an otherwise independent wave.
- [ ] EC-PARSCHED-3 — The roadmap lint reports an error when two phases with no DAG path between them share a Key file and no exclusion is declared; falsified by this roadmap's own overlaps going unreported.
- [ ] EC-PARSCHED-4 — Concurrent dispatch works with `manual` closeout; falsified by the concurrent scheduler refusing to start under manual closeout.

**Scope notes**
- Decompose into 3 lanes: lane A dispatcher (`compute_ready_phases`, submit-as-ready pool), lane B pairwise exclusion from the existing pairwise ownership diagnostics, lane C roadmap lint and ownership report. Lane A owns `runner.py` for this phase.
- Until this phase lands, the coordinator runs this roadmap's wave-1 phases concurrently by hand in separate worktrees.

**Non-goals**
- Cross-repo dispatch (`convergence/dispatch.py`).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/discovery.py`
- `phase-loop-runtime/src/phase_loop_runtime/worker_pool.py`
- `phase-loop-runtime/src/phase_loop_runtime/plan_ir.py`
- `phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py`
- `phase-loop-runtime/src/phase_loop_runtime/roadmap_ownership.py`

**Depends on**
- (none)

**Produces**
- IF-0-PARSCHED-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 4 — Split the Panel Invoker (PANELSPLIT)

**Objective**
Turn `panel_invoker.py` into a package of modules with separate owners, so panel-related phases stop serializing on one file.

**Exit criteria**
- [ ] EC-PANELSPLIT-0 — The existing test suite, unchanged, is the receipt: it passes before and after with no test file edited. (A behaviour-preserving move has no new tests to freeze, so this replaces the content-bound receipt of principle 6.)
- [ ] EC-PANELSPLIT-1 — `panel_invoker.py` is a facade of at most 1,500 lines; falsified by a line count above it.
- [ ] EC-PANELSPLIT-2 — Every name tests monkeypatch on `panel_invoker` still takes effect (late binding through the facade); falsified by a patched seam that the moved code no longer calls.
- [ ] EC-PANELSPLIT-3 — Each carried phase that named `panel_invoker.py` names the specific modules it owns in its v11 phase plan, and no two independent phases claim the same module; falsified by the PARSCHED lint.

**Scope notes**
- Single lane: a mechanical move in one PR, so in-flight branches rebase once. Module boundaries follow the existing chunks: president ladder, request and result types, verdict contract, redaction and logs, artifact ingestion, seat launch, broker builders, Claude TUI session, native fill, leg execution, spawn, board orchestration.
- Announce the landing; `claude/claude-print-route-plan` and agent-harness#1284 land before it or rebase onto it.

**Non-goals**
- Any behaviour change.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel/`

**Depends on**
- (none)

**Produces**
- IF-0-PANELSPLIT-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 5 — Isolation and Verification Hardening (HARDEN)

**Objective**
Carried from V10 Phase 6: finish the SL-5 evidence repair and the SL-6 completion seal.

**Exit criteria**
- [ ] EC-HARDEN-0 — Carried; as defined in V10.
- [ ] EC-HARDEN-6 — Replaces EC-HARDEN-5: a review seat holds only the capability its seat profile declares, a board path runs only with a valid review-isolation authorization, and any deliberately credentialed or tooled seat is recorded on the verdict; falsified by an undeclared capability or an unauthorized board path.

**Scope notes**
- EC-HARDEN-1 to -4 are met (agent-harness#737) and not carried.
- EC-HARDEN-5 is retired as written: the per-seat jail (agent-harness#1133, agent-harness#1282) gives seats their own credential and tools by design, so "no credentialed capability" cannot be met. EC-HARDEN-6 is the replacement, ratified by the maintainer on 2026-10-08.
- Single lane: SL-5 (agent-harness#1264, agent-harness#1351) then SL-6; both own only `scripts/` and `plans/`.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/scripts/verify_harden_evidence.py`
- `phase-loop-runtime/scripts/build_harden_evidence.py`

**Depends on**
- (none)

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 6 — Runtime Substrate (RUNTIME)

**Objective**
Carried from V10 Phase 10: replace the lost tests-first evidence and finish live reconciliation.

**Exit criteria**
- [ ] EC-RUNTIME-0 — Carried; as defined in V10, discharged under the evidence-loss policy of agent-harness#1000 once ratified.
- [ ] EC-RUNTIME-2 — Carried; as defined in V10.

**Scope notes**
- EC-RUNTIME-1, -3, -4, -5 are met (agent-harness#719, agent-harness#863, agent-harness#908) and not carried.
- Decompose into 2 lanes: lane A evidence-loss policy and EC-0; lane B live probes and the registry positive control for EC-2.

**Non-goals**
- The INTEG-owned transition-version binding (agent-harness#720 items 4–5).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/status.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py`

**Depends on**
- (none)

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 7 — President Execution Route (PRESROUTE)

**Objective**
Carried from V10 Phase 14 for closeout only: every goal but the receipt is met.

**Exit criteria**
- [ ] EC-PRESROUTE-0 — Carried; as defined in V10, with the frozen-test edits from `e2dff674` and `da9502b3` recorded as `sl0_repairs` entries.

**Scope notes**
- EC-PRESROUTE-1 to -5 are met (agent-harness#998, agent-harness#1035) and not carried.
- Single lane: ledger repair entries and the completion record. Widen agent-harness#1143 to cover both edits.

**Non-goals**
- agent-harness#1006, agent-harness#1206 (follow-ups, not goals).

**Key files**
- `.phase-loop/evidence/PRESROUTE/`

**Depends on**
- (none)

**Produces**
- IF-0-PRESROUTE-1

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 8 — Flexible Routing and Author-Aware Review (ROUTE)

**Objective**
Let the executor route each job, lane and phase to any vendor, model and effort through a routing policy with fallbacks, and keep review independent of the author without blocking on it.

**Exit criteria**
- [ ] EC-ROUTE-0 — Content-bound TDD receipt for this phase's tests, recorded before production changes.
- [ ] EC-ROUTE-1 — Each dispatched work unit (phase, lane or job) resolves its executor, model and effort through one routing call with an ordered fallback chain, and the decision is logged; falsified by a dispatch that picks a model outside the routing call or leaves no route record.
- [ ] EC-ROUTE-2 — The routing call is a replaceable interface (IF-0-ROUTE-1): a test registers a custom router and every dispatch path uses it with no dispatch-code change; falsified by a path that bypasses the registered router.
- [ ] EC-ROUTE-3 — Work units in one phase may run on different vendors, and no rule pins a phase to a single author vendor; falsified by a concurrent run refused or serialized because its lanes use different vendors.
- [ ] EC-ROUTE-4 — Each lens seat prefers its listed vendor, skips a model that authored the reviewed diff when an alternative is available, and otherwise seats a fresh-context reviewer with the overlap recorded on the verdict; review never fails because every vendor authored some of the work; falsified by an author-overlap refusal, or an unrecorded author seat.
- [ ] EC-ROUTE-6 — A work unit may carry an optional spec scope (spec-graph `level`, node `kind`, and node or frontier `name`), and the router receives it; routing never keys on chunker boundary ids; falsified by a scoped work unit whose scope does not reach the router, or a route keyed on a chunker id.
- [ ] EC-ROUTE-5 — The president's primary rung is the frontier model of the vendor opposite the phase's top-level model (the phase-plan author; for a standalone PR, the authoring session's model), per IF-0-ROUTE-2; fallback goes to the other frontier model, then the existing ladder, and any fallback is recorded on the ruling; falsified by a same-vendor primary president or an unrecorded fallback.

**Scope notes**
- Decompose into 3 lanes: lane A routing interface and work-unit routing (EC-1, EC-2, EC-3), publishing IF-0-ROUTE-1 on day 1; lane B lens-seat author preference and removal of the author-vendor fail-closed rule (EC-4); lane C president selection (EC-5), publishing IF-0-ROUTE-2.
- The spec scope lets routing follow the spec hierarchy later (for example, one model for `architecture`-level intent, another for `detailed` components, another for `operation` nodes). Routing data stays outside the spec graph, keyed by node `name` or `logical_id`.
- Builds on the existing model-routing code (`profiles.py`, `route_policy/`, `route_log.py`); it does not replace the routing tables.
- EC-ROUTE-5 replaces the fixed built-in president order of EC-PRESROUTE-3 (V10) as the primary choice; that order becomes the fallback. The frozen ladder test changes through an `sl0_repairs` entry, which is why this phase depends on PRESROUTE.
- ROUTE and PANEL both write `composition.py`, `governed_review.py` and `runner.py`, so they never run together. EC-ROUTE-4 extends whichever seat composition is on `main` when it lands: PANEL's lane seating if PANEL landed first, otherwise the current lens cycle, which PANEL then carries forward.
- Until this phase lands, the coordinator keeps each phase's implementation to at most two vendors, because the current rule excludes every author vendor from the reviewer pool.

**Non-goals**
- A learned or cost-aware router. This phase provides the interface a later router plugs into.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/profiles.py`
- `phase-loop-runtime/src/phase_loop_runtime/route_policy/`
- `phase-loop-runtime/src/phase_loop_runtime/route_log.py`
- `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`

**Depends on**
- PANELSPLIT
- PRESROUTE

**Produces**
- IF-0-ROUTE-1
- IF-0-ROUTE-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 9 — Panel Vendor Fallback and Lanes (PANEL)

**Objective**
Carried from V10 Phase 18 unchanged: panels are seated by lane from whatever vendors are available.

**Exit criteria**
- [ ] EC-PANEL-1 — Carried; as defined in V10.
- [ ] EC-PANEL-2 — Carried; as defined in V10.
- [ ] EC-PANEL-3 — Carried; as defined in V10.
- [ ] EC-PANEL-4 — Carried; as defined in V10.
- [ ] EC-PANEL-5 — Carried; as defined in V10.
- [ ] EC-PANEL-6 — Carried; as defined in V10.
- [ ] EC-PANEL-7 — Carried; as defined in V10.

**Scope notes**
- EC-PANEL-0 is met (agent-harness#1092) and not carried. Remaining slices are SL-1, SL-1b, SL-2, SL-3 of the V10 plan; SL-1 work is on branch `claude/1078-panel-sl1`.
- Lanes follow the V10 plan's slices; SL-1 owns `config.py`, `composition.py`, `presets.py`.
- Depends on PRESROUTE because SL-1's frozen-test authorization (`agent-harness#1078:PANEL-SL1:PRESROUTE`) can land only after PRESROUTE records the `da9502b3` repair.
- Overlaps with independent phases are listed under Execution Notes.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`

**Depends on**
- PRESROUTE

**Produces**
- IF-0-PANEL-1

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 10 — Scheduler and Worktree Reclamation (SCHED)

**Objective**
Carried from V10 Phase 5: close the evidence and regression gaps left after its runtime landed.

**Exit criteria**
- [ ] EC-SCHED-0 — Carried; as defined in V10.
- [ ] EC-SCHED-5 — Carried; as defined in V10.
- [ ] EC-SCHED-7 — Carried; as defined in V10. The two protected branches were deleted from `origin`; restore them from `refs/pull/97/head` and `refs/pull/98/head` or record the decision.

**Scope notes**
- EC-SCHED-1 to -4 and -6 are met (agent-harness#706) and not carried.
- Fix the frozen launcher test that fails on `main` since `da9502b3` (`_launch_with_lease_supervisor` gained required arguments) through an `sl0_repairs` entry.
- Decompose into 2 lanes: lane A regression and receipts (EC-0, EC-5); lane B branch restoration and SL-6 evidence (EC-7).

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/tests/test_phase_loop_launcher.py`

**Depends on**
- HARDEN

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 11 — Reflection Loop Applied (REFLOOP)

**Objective**
Run the repaired reflection loop end to end on the live backlog and keep it running.

**Exit criteria**
- [ ] EC-REFLOOP-0 — Content-bound TDD receipt for this phase's tests, recorded before production changes.
- [ ] EC-REFLOOP-1 — The skill editor applies an approved improvement plan generated from the live corpus, and the bundle gates pass; falsified by an applied plan that fails the parity or drift gate.
- [ ] EC-REFLOOP-2 — Consumed reflections are archived; a fresh collect reports `due=false` until new reflections arrive; falsified by re-aggregating archived reflections.
- [ ] EC-REFLOOP-3 — `maintain-skills` runs automatically when the threshold is met, at most once per interval; falsified by a due corpus with no planner run inside the interval.
- [ ] EC-REFLOOP-4 — Reflections record which skills the run read, and the aggregator applies a skill-was-used gate; falsified by an accepted recommendation for a skill the run did not read.
- [ ] EC-REFLOOP-5 — No skill points at `*-config/shared/runtime-state.md`; falsified by any such reference in `skills-src/`.
- [ ] EC-REFLOOP-6 — Every mechanism candidate the plan produced is filed as a qualified issue (`docs/registers/deferred-findings.md`) or delivered by LOOPFIX; falsified by a candidate with neither.

**Scope notes**
- Decompose into 3 lanes: lane A apply and archive (EC-1, EC-2); lane B trigger and run-context field (EC-3, EC-4); lane C dead references and mechanism routing (EC-5, EC-6).
- Owns `skills-src/` except the plan-phase skill, which LOOPFIX owns.
- Handoff 05's PStack items enter only through the aggregator's admission gates.

**Non-goals**
- Editing skills outside an approved plan.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/reflection_corpus.py`
- `phase-loop-runtime/src/phase_loop_runtime/maintenance.py`
- `skills-src/`

**Depends on**
- LOOPFIX

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none;
`redaction_posture: metadata_only`; malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 12 — Coordinator Integration and Fault Suite (INTEG)

**Objective**
Carried from V10 Phase 11 unchanged.

**Exit criteria**
- [ ] EC-INTEG-0 — Carried; as defined in V10.
- [ ] EC-INTEG-1 — Carried; as defined in V10.
- [ ] EC-INTEG-2 — Carried; as defined in V10.
- [ ] EC-INTEG-3 — Carried; as defined in V10.
- [ ] EC-INTEG-4 — Carried; as defined in V10.
- [ ] EC-INTEG-5 — Carried; as defined in V10.
- [ ] EC-INTEG-6 — Carried; as defined in V10.
- [ ] EC-INTEG-7 — Carried; as defined in V10.

**Scope notes**
- Decompose into 2 lanes as V10 does: lane A coordinator integration, lane B the fault suite. Includes agent-harness#720 items 4–5.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`

**Depends on**
- RUNTIME

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 13 — Board Reports Its Own Degradation (REVIEWTRUTH)

**Objective**
Carried from V10 Phase 7, on the split panel modules and the bounded review loop.

**Exit criteria**
- [ ] EC-REVIEWTRUTH-0 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-1 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-2 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-3 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-4 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-5 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-6 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-7 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-8 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-9 — Carried; as defined in V10. Its skill reference resolves to `skills-src/*/*-advisor-board/SKILL.md`.
- [ ] EC-REVIEWTRUTH-10 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-11 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-12 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-13 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-15 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-16 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-17 — Carried; as defined in V10.
- [ ] EC-REVIEWTRUTH-18 — Carried; as defined in V10.

**Scope notes**
- EC-REVIEWTRUTH-14 is met (agent-harness#921) and not carried. EC-6 is met today but carried as a regression guard to re-check at closeout.
- Publish IF-0-REVIEWTRUTH-1 (typed leg statuses) on day 1 so LEGLIFE's plan can start against it.
- EC-REVIEWTRUTH-8 (the production `apply_fix` fix round) is the loop accelerator in this phase; schedule its lane first.
- Depends on ROUTE so seat-composition and author rules are settled first; EC-REVIEWTRUTH-16 (required prover) is reconciled with ROUTE's president rule in this phase's plan.
- Lanes own disjoint `phase_loop_runtime/panel/` modules (IF-0-PANELSPLIT-1): verdict and classification, leg execution, board orchestration.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel/`
- `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_bundle.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`
- `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py`
- `phase-loop-runtime/src/phase_loop_runtime/review_summary.py`

**Depends on**
- PANELSPLIT
- REVBOUND
- PANEL
- ROUTE

**Produces**
- IF-0-REVIEWTRUTH-1
- IF-0-REVIEWTRUTH-2
- IF-0-REVIEWTRUTH-3

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 14 — Pilots and Governed Release (RELEASE)

**Objective**
Carried from V10 Phase 12 unchanged.

**Exit criteria**
- [ ] EC-RELEASE-0 — Carried; as defined in V10.
- [ ] EC-RELEASE-1 — Carried; as defined in V10.
- [ ] EC-RELEASE-2 — Carried; as defined in V10.
- [ ] EC-RELEASE-3 — Carried; as defined in V10.
- [ ] EC-RELEASE-4 — Carried; as defined in V10.
- [ ] EC-RELEASE-5 — Carried; as defined in V10.
- [ ] EC-RELEASE-6 — Carried; as defined in V10.

**Scope notes**
- Decompose into 2 lanes as V10 does: lane A pilots, lane B release mechanics, with lane B's publication after lane A's pilots.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/pyproject.toml`
- `CHANGELOG.md`
- `docs/releases/`

**Depends on**
- INTEG

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 15 — Leg Lifecycle and Board Extensibility (LEGLIFE)

**Objective**
Carried from V10 Phase 8 unchanged.

**Exit criteria**
- [ ] EC-LEGLIFE-0 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-1 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-2 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-3 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-4 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-5 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-6 — Carried; as defined in V10.
- [ ] EC-LEGLIFE-7 — Carried; as defined in V10.

**Scope notes**
- Depends on REVIEWTRUTH for IF-0-REVIEWTRUTH-1 only.
- Lanes own the leg-execution, spawn and Claude TUI session modules of `phase_loop_runtime/panel/`, disjoint from REVIEWTRUTH's.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel/`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing_omnigent.py`

**Depends on**
- REVIEWTRUTH

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 16 — Executable Findings (EXECFIND)

**Objective**
Carried from V10 Phase 15: restore the receipt and land the fix-round slice.

**Exit criteria**
- [ ] EC-EXECFIND-0 — Carried; as defined in V10, with an `sl0_repairs` entry for the agent-harness#1292 edit.
- [ ] EC-EXECFIND-2 — Carried; as defined in V10 as amended by its 2026-09-25 advisory ruling.
- [ ] EC-EXECFIND-6 — Carried; as defined in V10 as amended by its 2026-09-25 advisory ruling.

**Scope notes**
- EC-EXECFIND-1, -3, -4, -5 are met (agent-harness#1163, agent-harness#1164) and not carried.
- EC-6 needs EC-REVIEWTRUTH-8's production `apply_fix`; that is why this phase depends on REVIEWTRUTH.
- Decompose into 2 lanes: lane A receipt repair (EC-0, EC-2); lane B SL-3 fix round and SL-4 (branch `codex/v10-execfind-sl4-20260925`).

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/falsifier.py`
- `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel/`

**Depends on**
- REVIEWTRUTH

**Produces**
- IF-0-EXECFIND-1

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 17 — Broker, Train, and Channel Residuals (RESIDUAL)

**Objective**
Carried from V10 Phase 9 unchanged; its RED tests are already on `main`.

**Exit criteria**
- [ ] EC-RESIDUAL-0 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-1 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-2 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-3 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-4 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-5 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-6 — Carried; as defined in V10.
- [ ] EC-RESIDUAL-7 — Carried; as defined in V10. The F841 inventory is re-derived at planning time.

**Scope notes**
- Lanes follow the V10 plan's SL-1 to SL-5; SL-3's panel edits target the split modules.
- Depends on REVIEWTRUTH because both write `runner.py`, `cli.py`, `launcher.py` and the panel modules; as debt work it goes second.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`
- `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel/`
- `ruff.toml`

**Depends on**
- HARDEN
- PANELSPLIT
- REVIEWTRUTH

**Produces**
- (none)

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 18 — Ratification Tiers and Ruling Ledger (RATIFY)

**Objective**
Carried from V10 Phase 16 unchanged; its plan is in agent-harness#1203.

**Exit criteria**
- [ ] EC-RATIFY-0 — Carried; as defined in V10.
- [ ] EC-RATIFY-1 — Carried; as defined in V10.
- [ ] EC-RATIFY-2 — Carried; as defined in V10.
- [ ] EC-RATIFY-3 — Carried; as defined in V10.
- [ ] EC-RATIFY-4 — Carried; as defined in V10.
- [ ] EC-RATIFY-5 — Carried; as defined in V10.

**Scope notes**
- Decompose into 2 lanes as V10 does: lane A prompt partition, ruling classes and gate posture; lane B the ruling ledger. Plan in agent-harness#1203; SL-0 is agent-harness#1208.

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`
- `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py`
- `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`
- `phase-loop-runtime/src/phase_loop_runtime/ruling_ledger.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel/`
- `plans/rulings.jsonl`
- `skills-src/`

**Depends on**
- EXECFIND
- PRESROUTE

**Produces**
- IF-0-RATIFY-1

**Spec closeout policy**
As in V10 for this phase.

---

### Phase 19 — Governance Profile at Setup (GOVSETUP)

**Objective**
Carried from V10 Phase 17 unchanged.

**Exit criteria**
- [ ] EC-GOVSETUP-0 — Carried; as defined in V10.
- [ ] EC-GOVSETUP-1 — Carried; as defined in V10.
- [ ] EC-GOVSETUP-2 — Carried; as defined in V10.
- [ ] EC-GOVSETUP-3 — Carried; as defined in V10.
- [ ] EC-GOVSETUP-4 — Carried; as defined in V10.
- [ ] EC-GOVSETUP-5 — Carried; as defined in V10.
- [ ] EC-GOVSETUP-6 — Carried; as defined in V10.

**Scope notes**
- Decompose into 2 lanes as V10 does: lane A schema, resolver and CLI consumers; lane B installer, `init` and `doctor`. Its profile schema must fit PANEL's layout (V10 PANEL ruling, 2026-09-27).

**Non-goals**
- As in V10.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/governance_profile.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`
- `docs/TEAM-ONBOARDING.md`

**Depends on**
- RATIFY
- PANEL

**Produces**
- IF-0-GOVSETUP-1

**Spec closeout policy**
As in V10 for this phase.

## Phase Dependency DAG

```
Wave 1 (roots, all parallel)
  TESTLOOP  LOOPFIX  REVBOUND  PARSCHED  PANELSPLIT  HARDEN  RUNTIME  PRESROUTE

Wave 2
  PRESROUTE ─▶ PANEL
  PANELSPLIT, PRESROUTE ─▶ ROUTE
  HARDEN ────▶ SCHED
  LOOPFIX ───▶ REFLOOP
  RUNTIME ───▶ INTEG

Wave 3
  PANELSPLIT, REVBOUND, PANEL, ROUTE ─▶ REVIEWTRUTH
  INTEG ─▶ RELEASE

Wave 4
  REVIEWTRUTH ─▶ LEGLIFE
  REVIEWTRUTH ─▶ EXECFIND
  REVIEWTRUTH, HARDEN, PANELSPLIT ─▶ RESIDUAL

Wave 5
  EXECFIND, PRESROUTE ─▶ RATIFY

Wave 6
  RATIFY, PANEL ─▶ GOVSETUP
```

Edges:
- PRESROUTE → PANEL
- PANELSPLIT → ROUTE
- PRESROUTE → ROUTE
- ROUTE → REVIEWTRUTH
- HARDEN → SCHED
- LOOPFIX → REFLOOP
- RUNTIME → INTEG
- PANELSPLIT → REVIEWTRUTH
- REVBOUND → REVIEWTRUTH
- PANEL → REVIEWTRUTH
- INTEG → RELEASE
- REVIEWTRUTH → LEGLIFE
- REVIEWTRUTH → EXECFIND
- REVIEWTRUTH → RESIDUAL
- HARDEN → RESIDUAL
- PANELSPLIT → RESIDUAL
- EXECFIND → RATIFY
- PRESROUTE → RATIFY
- RATIFY → GOVSETUP
- PANEL → GOVSETUP

Critical path: PRESROUTE → PANEL → REVIEWTRUTH → EXECFIND → RATIFY → GOVSETUP (six phases;
v10's was ten). PRESROUTE is a single ledger change, so in practice the path starts at PANEL.
Wave 1 runs eight phases in parallel.

## Execution Notes

- **Schedulers.** Until PARSCHED lands, the coordinator runs ready phases concurrently by hand in
  separate worktrees. After it lands, run with `--phase-scheduler concurrent`; the lane
  scheduler is also on.
- **Executors and review.** One model writes each phase plan; the plan is reviewed through the
  four lens seats, each with a preferred vendor and fallbacks (PANEL). Execution is not tied to a
  vendor: the executor routes each job, lane and phase to the model and effort it judges best,
  through the routing policy (ROUTE). v10's author-vendor rotation does not carry. Review tiers
  are as on `main` (full board plus president for plans and production code, one grounded
  reviewer for tests-only and docs-only), with author-aware seats and an opposite-vendor
  president once ROUTE lands. V10's rule that a 3-of-4 board never authorizes a landing stays in
  force until REVIEWTRUTH enforces it at runtime.
- **Planning.** Each phase gets `plans/phase-plan-v11-<ALIAS>.md`. A carried phase's plan
  references its V10 plan as a frozen input and covers only the remaining slices; it does not
  restate V10 goals. Carried plans name the specific `phase_loop_runtime/panel/` modules they
  own (EC-PANELSPLIT-3), which removes most `panel/` overlaps below.
- **Overlaps between independent phases.** Each pair below shares a Key file but has no
  dependency path between them. The pair must not run concurrently; neither waits for the other
  to finish. Paths are relative to `phase-loop-runtime/src/phase_loop_runtime/` unless they start
  at the repo root. The list is derived from this roadmap's Key files; EC-PARSCHED-3 makes the
  check mechanical.
  - TESTLOOP / RELEASE: `phase-loop-runtime/pyproject.toml`
  - LOOPFIX / PANEL, REVIEWTRUTH, RESIDUAL, GOVSETUP: `cli.py`
  - LOOPFIX / RATIFY: `plan_manifest.py`, `skills-src/ (plan-phase and execute-phase scripts)`
  - PARSCHED / ROUTE, PANEL, REVIEWTRUTH, EXECFIND, RESIDUAL: `runner.py`
  - ROUTE / PANEL: `advisor_board/composition.py`, `governed_review.py`, `runner.py`
  - PANEL / INTEG, RELEASE: `train_runner.py`
  - SCHED / REVIEWTRUTH, RESIDUAL: `launcher.py`
  - REFLOOP / RATIFY: `skills-src/`
  - INTEG / RESIDUAL: `convergence/broker/verbs.py`, `train_runner.py`
  - RELEASE / RESIDUAL: `train_runner.py`
  - LEGLIFE / EXECFIND, RESIDUAL, RATIFY: `panel/`
  - EXECFIND / RESIDUAL: `panel/`, `runner.py`
  - RESIDUAL / RATIFY: `panel/`
  - RESIDUAL / GOVSETUP: `cli.py`
- **Single-writer files.** `plans/manifest.json`: every phase appends its own rows and none
  rewrites another phase's. `specs/phase-plans-v11.md`: changed only by amending `Depends on`
  or by an explicit goal retirement.
- **Abort threshold.** If a phase lands three plan-amendment PRs before its first
  implementation PR, stop that phase and diagnose (`docs/agent-phase-convergence.md`).

## Verification

```bash
# This roadmap parses, its DAG is acyclic, and the registry selects it
uv run --quiet --with-editable ./phase-loop-runtime phase-loop validate-roadmap specs/phase-plans-v11.md

# Whole-suite regression on a team host: 0 failures, 0 errors (EC-TESTLOOP-4)
uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q

# Goal coverage: every open goal ID is referenced by a v11 phase plan
uv run --quiet --with-editable ./phase-loop-runtime phase-loop goal-coverage-audit --roadmap specs/phase-plans-v11.md

# Concurrent dispatch is on and readiness-driven (EC-PARSCHED-1)
uv run --quiet --with-editable ./phase-loop-runtime phase-loop dry-run --phase-scheduler concurrent --json
```
