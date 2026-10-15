---
phase_loop_plan_version: 1
phase: PARSCHED
roadmap: specs/phase-plans-v11.md
roadmap_sha256: d294c3bab92c995bda8266a12340c78a9d73c12a18919a47b2154ceb4555aba4
automation:
  suite_command: "uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q"
---

# PARSCHED: Readiness-Driven Concurrent Phase Dispatch

## Context

Implement Phase 3 of the selected roadmap; EC-PARSCHED-0 through EC-PARSCHED-5 remain authoritative there. There are no upstream phase dependencies.

Current construction sites are `runner.run_loop._dispatch_concurrent_wave`, `discovery.compute_ready_phases`, `discovery.validate_concurrent_phase_ownership`, `worker_pool.run_phase_worker_pool`, `plan_ir._patterns_overlap_any`, `roadmap_lint.lint_roadmap_text`, and `roadmap_ownership.ownership_map`. The runner selects a topological wave, serializes it on any ownership diagnostic, waits for every worker, and rejects manual closeout when real-exec integration is enabled. The existing readiness helper is not wired into that dispatch path.

Use the roadmap's three implementation lanes, preceded by a tests-only preamble and followed by a docs/evidence reducer. Cross-repo dispatch, model routing, enabling concurrency by default, and consuming greenfield wave schedules are outside scope. Canonical `.phase-loop/` is authoritative; legacy state cannot override it.

## External Inputs

- `specs/phase-plans-v11.md`, bound by frontmatter; do not amend it during this phase.
- Greenfield `parallel_lane_graph.v0.1`, published by ViperJuice/greenfield, pinned by external content: `spec/parallel-lane-graph-spec.md` SHA-256 `d7e993e64ea7123662d09eb6f0eb19d3b1bf541e1c61dc34fb9423b82f245e68`; `greenfield/parallel_lane_ownership.py` SHA-256 `1ca1523fbf8240fcd34069b9dafd9afd2d84b4c105aaae49d80adfe2c7499c44`; `greenfield/resource_capability.py` SHA-256 `f649d5c2ff1f8c256c0741e201e0219a90d93874dea1f02096e318fca35f20fc`; `tests/test_parallel_lane_graph_ownership.py` SHA-256 `a5adf3830b6c9246725a2c01fdfcbe0593d7cc1584f7b902fb7f5a7f1624f707`; `tests/fixtures/parallel_lane_graph/ownership_cases.json` SHA-256 `5d0ab13408c059d0c9b42387e4f88cd2a4b6677404ccd0f74a2a274e42f8db10`; `tests/fixtures/resource_capability/cases.json` SHA-256 `b054d41b2c377a2658784b734b40eec5b3fa42c36e43135742dba2f6637529a2`.
- SL-0 copies the applicable published fixtures and records upstream paths, hashes, and expected outcomes under its owned fixture directory. Retrieve that exact input through Git or the GitHub contents API; a local checkout is a cache, not a required machine path. No greenfield runtime dependency or source edit.

## Interface Freeze Gates

- [ ] IF-0-PARSCHED-1 — Freeze these production contracts after all lane evidence passes:
  - `compute_ready_phases(roadmap, classifications, completed)` keeps its call signature and roadmap ordering. The coordinator excludes in-flight, blocked, completed, and preserved-awaiting-closeout generations, re-evaluates readiness after each finalized result, and submits every admissible candidate up to available capacity in that tick. Only trusted, verified completion satisfies a dependency.
  - `plan_ir._patterns_overlap_any(left_patterns, right_patterns, *, left_reads=(), right_reads=(), concurrent=True) -> bool` becomes the shared predicate. Existing positional callers remain valid. Exact paths, directory boundaries, globs, and conservative uncertain intersections follow the pinned fixtures. Read/read access is compatible; write/read overlap conflicts during simultaneous execution, while read-only neighbour facts outside it do not grant writes or create write/write conflicts.
  - `validate_concurrent_phase_ownership(repo, roadmap, aliases)` retains pairwise `LaneIRDiagnostic` results with `details.left` and `details.right`. Dispatch excludes only a conflicting candidate against running or newly admitted phases; a declared exclusion never authorizes overlapping writes.
  - `worker_pool.PhaseWorkerPool(repo, roadmap, *, max_workers=None)` supplies `submit(job)`, `poll_completed(*, timeout=0.0) -> tuple[PhaseWorkerResult, ...]`, and `close()`. The existing batch `run_phase_worker_pool` signature and ordered result contract remain supported. Every submitted writer has a scheduler-created worktree handle and generation lease.
  - `roadmap_lint.lint_roadmap_text` enables the new independent Key-file overlap error only for roadmaps carrying the `Overlaps between independent phases` declaration in Execution Notes; declaration presence enables it even with no exclusion entries. Within that scope, the pair and shared scope must be explicitly excluded. Roadmaps without the declaration retain existing lint behavior, preserving v10 `ownership_map`/`replay`/`audit` compatibility. Ownership reporting and lint share normalized pair/path facts; `ownership_map` retains fatal-on-any-lint-error behavior, surfacing diagnostic facts in `RoadmapUnreadable` instead of returning a map for invalid opted-in roadmaps. Existing v11 grouped declarations and runtime-relative path shorthand are supported; dependency reachability is transitive.
  - Manual closeout preserves verified output, generation identity, staged/untracked bytes, and leases in its worktree with `awaiting_phase_closeout`. It neither commits nor transports dirty output onto the coordinator branch; independent work continues, and dependents wait for actual completion. Existing commit/push reduction remains serialized and trusted.

## Lane Index & Dependencies

SL-0 — Tests and input freeze
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4
  Parallel-safe: no

SL-1 — Pairwise ownership predicate
  Depends on: SL-0
  Blocks: SL-2, SL-3, SL-4
  Parallel-safe: no

SL-2 — Readiness dispatcher and incremental pool
  Depends on: SL-0, SL-1
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Roadmap overlap lint and ownership report
  Depends on: SL-0, SL-1
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Docs and phase evidence reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Tests and input freeze

- **Scope**: Freeze all behavior tests, compatibility fixtures, and the content-bound RED receipt before production changes.
- **Owned files**: `phase-loop-runtime/tests/test_parsched_*.py`, `phase-loop-runtime/tests/parsched_freeze_receipt.py`, `phase-loop-runtime/tests/fixtures/parsched/**`, `phase-loop-runtime/tests/test_phase_loop_v45_found_contracts.py`, `phase-loop-runtime/tests/test_phase_loop_v45_sched.py`, `phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py`, `phase-loop-runtime/tests/test_workerpool_parallel.py`, `phase-loop-runtime/tests/test_workerpool_failure_isolation.py`, `phase-loop-runtime/tests/test_workerpool_worktree_alloc.py`, `phase-loop-runtime/tests/test_phase_loop_discovery.py`, `phase-loop-runtime/tests/test_phase_loop_runner.py`, `phase-loop-runtime/tests/test_phase_loop_lane_ir.py`, `phase-loop-runtime/tests/test_phase_loop_lane_ir_fixtures.py`, `phase-loop-runtime/tests/test_phase_loop_roadmap_validate.py`, `phase-loop-runtime/tests/test_roadmap_ownership.py`, `phase-loop-runtime/tests/test_phase_loop_baml_v1_callers.py`, `phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py`, `.phase-loop/evidence/PARSCHED/content-tdd-receipt.json`, `.phase-loop/evidence/PARSCHED/content-tdd-receipt.red.stdout.log`, `.phase-loop/evidence/PARSCHED/content-tdd-receipt.red.stderr.log`
- **Interfaces provided**: `PARSCHED-TESTS`
- **Interfaces consumed**: `IF-0-GOVLEAN-1` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add `test_parsched_scheduler.py`, `test_parsched_overlap.py`, `test_parsched_roadmap.py`, and `test_parsched_evidence.py`. Use deterministic events/barriers and a controllable tick; bound waits for cleanup, without timing-based success assertions. Every integration test must assert entry to the real production construction site.
  - test: Exercise A and unrelated B running, C depending only on A, and C admitted while B remains held; A/B overlap with independent D still running; failed/blocked A never releasing C; no duplicate submissions; capacity refill; operator stop; worker exception cleanup; trusted transfer conflict and stale generation preservation. Test manual mode both with and without real-exec integration enabled, plus commit/push regressions.
  - test: Assert published exact/glob/read-neighbour outcomes, glob/glob and directory-boundary controls, missing versus genuinely empty ownership, direct/transitive dependencies, grouped exclusions, undeclared/wrong-path exclusions, and all current v11 overlap declarations. Update only legacy assertions superseded by these goals; retain lease, ownership, and closeout safety assertions.
  - test: Freeze compatibility controls in `test_parsched_roadmap.py`: unchanged `specs/phase-plans-v10.md` has no lint errors and `ownership_map` retains SCHED/HARDEN as `runner.py` owners. Retain all five real-v10 reads and existing replay/audit regressions in `test_roadmap_ownership.py`. Cover a declaration with no exclusion entries and `RoadmapUnreadable` pair/path diagnostics for invalid opted-in text.
  - impl: Copy external fixtures unchanged and add provenance metadata. Implement a thin receipt helper around `tdd_receipts.record_content_tdd_receipt`, including all changed test/support/fixture bytes in its support inventory. Honor its existing activation variable and literal RED-anchor requirement; retain genuine behavioral failures separately from that anchor. Resolve the tests-only landing input at recording time; prescribe no future SHA, commit count, or topology.
  - verify: Collect every frozen node, obtain pytest exit 1 from behavioral RED assertions rather than import/collection failures, then record and verify the receipt before SL-1 begins. Use `uv run --quiet --with-editable ./phase-loop-runtime python -m phase_loop_runtime.tdd_receipts verify --receipt .phase-loop/evidence/PARSCHED/content-tdd-receipt.json --repo .`. Preserve logs and frozen bytes; any required legacy frozen-test repair uses existing governed repair evidence before resealing.

### SL-1 — Pairwise ownership predicate

- **Scope**: Make the existing ownership comparison reusable and consistent with the pinned greenfield input.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/plan_ir.py`
- **Interfaces provided**: `PARSCHED-OVERLAP`
- **Interfaces consumed**: `PARSCHED-TESTS`
- **Parallel-safe**: no
- **Tasks**:
  - test: Run the frozen overlap tests against existing comparison logic and retain path-entered mismatches.
  - impl: Extend `_patterns_overlap_any` and its existing helpers with the frozen access semantics; keep lane ownership diagnostics using this predicate. Preserve conservative conflict reporting without conflating sibling directory prefixes. Do not expand glob ownership solely against today's tracked files, since writers can create files.
  - verify: `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k 'parsched_overlap or phase_loop_lane_ir'`; compare every fixture to its recorded upstream expectation.

### SL-2 — Readiness dispatcher and incremental pool

- **Scope**: Replace the concurrent wave barrier with a coordinator-owned submit/poll loop and preserve safe manual closeout.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/discovery.py`, `phase-loop-runtime/src/phase_loop_runtime/worker_pool.py`
- **Interfaces provided**: `PARSCHED-DISPATCH`
- **Interfaces consumed**: `PARSCHED-TESTS`, `PARSCHED-OVERLAP`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Run frozen readiness, pair-exclusion, manual-closeout, and pool lifecycle tests through `run_loop`, not a replacement scheduler.
  - impl: Use `compute_ready_phases` and an incremental pool; route discovery's duplicate overlap logic through SL-1. Validate each executable plan's ownership before admission; unplanned work may plan in isolation but unknown ownership must never be treated as a disjoint executable plan. Track submitted identities and ownership reservations until finalized or preserved.
  - impl: Keep prepare/finalize, state/ledger writes, and parent reductions on the coordinator thread. Workers receive immutable per-job context; shared `alias`/repo closure state must not race. Finalize each returned result before recomputing completed dependencies, using a fresh integrated base for newly admitted work. Do not use topological waves or greenfield `safe_waves` as dispatch units.
  - impl: Remove the manual startup refusal only together with worktree-local finalization/preservation. Do not mark a successful process exit, a planning result, or an awaiting-closeout child complete. Preserve the dispatch lock, trusted closeout checks, generation lease authority, recovery branches, explicit-phase behavior, full-phase/max-phases accounting, capacity bounds, and operator-stop handling.
  - verify: `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k 'parsched_scheduler or workerpool or v45_sched or v45_found_contracts'`. Force completion order and inspect admission, exclusion, and preservation metadata; do not infer concurrency from a dry-run.

### SL-3 — Roadmap overlap lint and ownership report

- **Scope**: Detect and explain undeclared independent-phase ownership conflicts using the shared predicate.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_ownership.py`
- **Interfaces provided**: `PARSCHED-LINT`
- **Interfaces consumed**: `PARSCHED-TESTS`, `PARSCHED-OVERLAP`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Run frozen roadmap tests with real v11 text and in-memory removal of each exclusion and then all exclusion entries, retaining the declaration; assert errors identify the affected pair/path while ordered phases remain exempt. Run the frozen v10 compatibility controls.
  - impl: Apply IF-0-PARSCHED-1's declaration gate only to the new overlap error. Normalize Key-file paths and declared exclusion scopes, compare all pairs without a DAG path in either direction, and expose shared normalized findings to ownership reporting. Support the existing grouped v11 syntax without amending the roadmap. Avoid both integration traps: `ownership_map` already invokes lint and makes every lint error fatal, so scope the error at its producer without suppressing errors in ownership consumers; lint must not import or call `ownership_map` recursively. Keep shared normalization on the lint side of that dependency.
  - verify: `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k 'parsched_roadmap or roadmap_ownership or phase_loop_roadmap_validate'`, followed by both explicit validate-roadmap commands below on unchanged v10 and v11 inputs.

### SL-4 — Docs and phase evidence reducer

- **Scope**: Verify the integrated result and synthesize operator documentation and metadata-only closeout evidence from every producer.
- **Owned files**: `phase-loop-runtime/README.md`, `plans/evidence/v11-PARSCHED/**`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-PARSCHED-1`
- **Interfaces consumed**: `PARSCHED-TESTS`, `PARSCHED-OVERLAP`, `PARSCHED-DISPATCH`, `PARSCHED-LINT`
- **Parallel-safe**: no
- **Tasks**:
  - test: Re-verify the frozen receipt and run all targeted commands before the whole suite. Evidence tests must reject missing receipt bindings, missing path-entered controls, incomplete goal coverage, and fabricated completion.
  - impl: Document concurrent readiness, pair exclusions, capacity, manual recovery, and unchanged scheduler defaults in the existing README. Write `plans/evidence/v11-PARSCHED/closeout.json` containing goal-to-command results, actual verification artifact references/digests, fixture provenance, and the produced gate; omit secrets and invented results. Apply `no_spec_delta`. Update only PARSCHED's manifest row through the append API, preserving other rows.
  - verify: Run the Verification section and effective suite command, inspect preserved-worktree controls, and verify receipt integrity again. Populate IF-0-PARSCHED-1 only on successful acceptance; report unresolved results accurately.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, unsupported=`inherit_default`, inherit-default=`true`
- SL-4: work-unit=`phase_reducer`, unsupported=`inherit_default`, inherit-default=`true`

## Execution Notes

1. Freeze SL-0 before production edits; SL-1 then supplies the predicate to both implementation consumers. SL-2 and SL-3 may overlap only after machine-validated disjoint ownership, explicit dependencies, and scheduler-owned worktree assignments. SL-4 is excluded from writer waves. A single executor can run all lanes sequentially; prose parallel-safety is not fanout authorization.
2. No same-wave or cross-lane owned-path overlap is permitted. Shared test/fixture edits belong solely to SL-0; no later lane changes frozen tests. The reducer alone owns shared documentation and the PARSCHED ledger update. Production model/schema files, CLI parsing, dependency/lock files, skill sources/bundles, environment examples, and migrations stay untouched because no option, dependency, persisted schema, or skill change is required. Existing CLI and plan-wave tests run as regression evidence.
3. Respect the roadmap's PARSCHED pair exclusions with ROUTE, PANEL, REVIEWTRUTH, EXECFIND, and RESIDUAL. Team-host worktrees use the existing resolver and private per-user root. Preserve failed or manual generations; never reclaim an active lease. Review remains under current repository policy, with ratified cross-vendor evidence required for a Sol-authored plan; this planning artifact does not assert review approval.
4. Policy precedence is CLI/operator override, phase-plan policy, roadmap policy, Dispatch Hints, then registry defaults. Explicit default inheritance above permits registry selection; any fallback outside that inheritance must be reason-coded, never a silent downgrade.
5. At intake validate command paths through IF-0-VC-2. Commands below deliberately target existing test directories/files; new test selectors become populated in SL-0. No operational-evidence exemption or proxy is used. Full-suite host failures must be diagnosed and reported, not hidden by new markers or skips.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none
- evidence paths: `plans/evidence/v11-PARSCHED/closeout.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

- `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k parsched`
- `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_phase_loop_v45_found_contracts.py phase-loop-runtime/tests/test_phase_loop_v45_sched.py phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py phase-loop-runtime/tests/test_workerpool_parallel.py phase-loop-runtime/tests/test_workerpool_failure_isolation.py phase-loop-runtime/tests/test_workerpool_worktree_alloc.py phase-loop-runtime/tests/test_phase_loop_lane_ir.py phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py phase-loop-runtime/tests/test_phase_loop_discovery.py phase-loop-runtime/tests/test_phase_loop_runner.py phase-loop-runtime/tests/test_phase_loop_cli.py phase-loop-runtime/tests/test_plan_ir_iter_waves.py phase-loop-runtime/tests/test_roadmap_ownership.py phase-loop-runtime/tests/test_phase_loop_roadmap_validate.py phase-loop-runtime/tests/test_dispatch_lock_same_roadmap.py -q`
- `uv run --quiet --with-editable ./phase-loop-runtime phase-loop validate-roadmap specs/phase-plans-v11.md`
- `uv run --quiet --with-editable ./phase-loop-runtime phase-loop validate-roadmap specs/phase-plans-v10.md`

The frontmatter suite command runs the whole runtime regression after targeted verification. Runtime verification artifacts and the SL-4 closeout record bind actual results to this phase. Receipt verification and its production-path mutation controls are also exercised by the new evidence tests selected above.

## Acceptance Criteria

- [ ] EC-PARSCHED-0 — proven by `uv run --quiet --with-editable ./phase-loop-runtime python -m phase_loop_runtime.tdd_receipts verify --receipt .phase-loop/evidence/PARSCHED/content-tdd-receipt.json --repo .`, falsified by a frozen-byte or RED-log mutation passing `tdd_receipts.verify_content_tdd_receipt`; path-entered control validates the intact receipt first.
- [ ] EC-PARSCHED-1 — proven by `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k parsched_ready_tick`, falsified by restoring wave selection or waiting for all futures inside `runner.run_loop`; path-entered control holds B, finalizes A, and requires C admission at the next tick.
- [ ] EC-PARSCHED-2 — proven by `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k parsched_pair_exclusion`, falsified by routing any ownership diagnostic to whole-wave serialization in the runner; path-entered control requires independent D to start while the A/B conflict is held.
- [ ] EC-PARSCHED-3 — proven by `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k parsched_roadmap`, falsified by removing a declared v11 exclusion while `roadmap_lint.lint_roadmap_text` remains clean; path-entered control validates intact declarations and checks both diagnostic aliases and path.
- [ ] EC-PARSCHED-4 — proven by `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k parsched_manual`, falsified by restoring the startup refusal, losing staged/untracked bytes, or releasing a dependent from awaiting closeout in `runner.run_loop`; path-entered control launches two distinct writer worktrees and verifies preserved generations.
- [ ] EC-PARSCHED-5 — proven by `uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k parsched_overlap`, falsified by a changed exact/glob/read-neighbour result from `plan_ir._patterns_overlap_any`; path-entered control calls the production predicate for every pinned fixture and its recorded expected result.
