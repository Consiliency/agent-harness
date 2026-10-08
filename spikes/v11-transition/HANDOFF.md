# Handoff — finishing the v11 roadmap (2026-10-08)

Branch: `claude/roadmap-v11`. Draft: `specs/phase-plans-v11.md`. Snapshot of in-flight work:
`spikes/v11-transition/inventory-2026-10-08.md`.

The draft passes the structural lint (`python -m phase_loop_runtime.roadmap_lint`). The full
`phase-loop validate-roadmap` still fails, as it should, because `specs/roadmap-status.json`
does not list v11 yet. v10 stays the active roadmap until step 3 below lands.

## Why v11 exists

v10 closed six phases in its first four weeks and none in the six after. Over that time it grew
from 8 to 19 phases and to about 36,000 words, and its critical path grew from 8 to 10 phases.
The work that would speed up our own loop (leg reaping, vendor fallback, autonomous rulings)
sat behind governance work. The roadmap's Context section has the measured friction. In short:
- `main` is red after about 27% of landings;
- review rounds don't converge;
- phases run one at a time because the schedulers are off and one shared file serializes a wave.

## Owner decisions (2026-10-08) — do not re-litigate

1. **Replace v10, don't amend it.** The delivered phases stay recorded. The unfinished phases
   are carried with their aliases and goal IDs unchanged, and are cited by ID against v10 at
   `9eb77a3d`, never restated.
2. **In-flight work.** Land the small PRs before the freeze; carry the large phases mid-slice.
   - Before the freeze: agent-harness#1323, agent-harness#1325, agent-harness#1328 and
     agent-harness#1350. The executive agent is merging these.
   - Carried mid-slice: HARDEN, PANEL, EXECFIND, RATIFY, REVIEWTRUTH.
3. **EC-HARDEN-5 is retired.** EC-HARDEN-6 replaces it and is ratified.
4. **Routing and review.**
   - One model writes each phase plan, and the plan is reviewed through the lens seats. Each
     lens has a preferred vendor and fallbacks.
   - Execution routes each job, lane and phase freely to any vendor, model and effort. v10's
     author-vendor rotation does not carry over.
   - Review tiers stay as they are on `main`.
   - Lens seats avoid models that authored the diff when an alternative exists. Review never
     blocks on author overlap; the overlap is recorded instead.
   - The president is always a frontier model. Its primary is the vendor opposite the
     top-level model of the phase plan; fallback goes to the other frontier vendor, then the
     ladder, and the fallback is recorded. This is ROUTE.
5. **PANELSPLIT stays in wave 1.** In-flight `panel_invoker.py` branches rebase onto it.
6. **No spec-compliance admission gate.**
   - The intended model is an adapter: the harness maintains its own spec of a client repo
     and writes it back when the work completes. Clients are never forced to comply.
   - That adapter, plus binding work units to spec frontiers and dispatching from greenfield
     lane graphs, is a joint follow-on roadmap across agent-harness, Consiliency/spec and
     greenfield.
   - v11 freezes only the hooks for it: ROUTE's spec scope and greenfield reference,
     PARSCHED's overlap predicate, and versioned shared contracts.
   - greenfield#48 tracks greenfield's move to a logical seam key.

## Findings that shaped the draft

- **v10 phases that are not ready to close:**
  - SCHED: a frozen launcher test fails on `main` since `da9502b3`, and the branches
    EC-SCHED-7 protects were deleted from `origin`.
  - RUNTIME: the EC-0 receipt is lost (agent-harness#720), and EC-2 is partial.
  - PRESROUTE: all goals are met, but two frozen-test edits lack `sl0_repairs` records.
  - EXECFIND: its receipt has drifted since agent-harness#1292.
- **Author-vendor exclusion.** `_phase_author_vendors` in `runner.py` excludes every author
  vendor from the review pool. Free routing would leave no reviewers, so ROUTE replaces this.
  Until ROUTE lands, keep each phase to at most two implementing vendors.
- **Consiliency/spec** runs its roadmaps through our phase-loop. Its plans use a lane-index form
  that the runtime parser accepts and the validator rejects. LOOPFIX must widen the validator,
  never narrow the parser.
- **`spec_delta_closeout.v1`** is copied by downstream plans but is defined only here, so it
  changes only by a new version.
- **greenfield** owns `parallel_work_unit.v0.1` and `parallel_lane_graph.v0.1`. ROUTE accepts
  units as hints, and PARSCHED's overlap predicate must agree with greenfield's fixtures.

## Remaining steps

1. **Wait for the four small PRs to merge**, then merge `origin/main` into this branch.
   Re-run the structural lint, and re-check the inventory snapshot for anything new.
2. **Re-derive anything that moved.** If a carried phase's goal was met by the merges, drop it
   from the phase. Never renumber; gaps are allowed.
3. **Supersession change**, in the same PR. A scratch-clone dry run confirmed this list:
   - `specs/roadmap-status.json`:
     - add `{"path":"specs/phase-plans-v11.md","status":"active"}`;
     - set v10 to `superseded` and `selected_roadmap` to v11;
     - keep the list path-sorted.
   - v10 line 3 becomes
     ``> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v11.md` (2026-10-08)``, followed by `>`
     and `> **Do not execute this roadmap.** …`, the same shape as v9's banner.
   - `phase_loop_runtime/roadmap_lint.py` `_BANNER_PATTERNS`: the superseded patterns hardcode
     `phase-plans-v10.md`. Add a v11 target and keep the v10 one for older roadmaps.
   - Reseal v10:
     `python -m phase_loop_runtime.roadmap_reseal --repo . --roadmap specs/phase-plans-v10.md --write`.
   - `plans/manifest.json`:
     - append one `plan_current_authority.v1` entry for each v10 plan row that has
       `plan_authority_history` (see agent-harness#1263);
     - refresh `roadmap_sha256` in the six plans that pin the current v10 digest;
     - mark v10's non-completed rows `orphaned`, as the convergence-v1 → v10 transition did.
   - Tests:
     - `test_legible_roadmap_contract.py`: the expected registry and banners, the count 13 → 14,
       and the active path. Do not rename tests; their node IDs are frozen.
     - `test_legible_review_repairs.py`: fixtures that copy v10 as active.
     - `test_roadmap_ownership.py`: the expected active roadmap name.
   - Delete any local `.phase-loop/state.json` that points at v10.
4. **Validate.**
   - `phase-loop validate-roadmap specs/phase-plans-v11.md`.
   - The LEGIBLE, ownership and roadmap-validate test files, plus
     `test_skills_canon_parity.py` and `test_skills_bundle_drift.py`.
   - The full suite fails on team hosts for environmental reasons that also fail on clean
     `main`. Compare failing test IDs against `main` rather than reading the total.
5. **Open one PR.** It needs governed review: a plan-tier landing gets the full board plus the
   president. Do not merge without maintainer authorization.
6. **After merge:** `/claude-plan-phase <ALIAS>` for the wave-1 phases, run concurrently in
   separate worktrees:
   - TESTLOOP, LOOPFIX, REVBOUND, PARSCHED, PANELSPLIT, HARDEN, RUNTIME, PRESROUTE.

## Constraints

- Shared team host: work only in your own worktree. Never reclaim another worktree; several
  hold other sessions' uncommitted work.
- `skills-src/` is canonical. Regenerate the bundles with the two scripts in
  `phase-loop-runtime/scripts/`.
- Write issue and PR references as `agent-harness#N`, never as a bare `#N`.
